##
# copyright 2009, James William Pye
# http://python.projects.postgresql.org
##
'PQ version 3.0 client transactions'
import sys
import os
from abc import ABCMeta, abstractmethod
from pprint import pformat
from itertools import chain
from operator import itemgetter
get0 = itemgetter(0)
get1 = itemgetter(1)

from ..python.functools import Composition as compose
from .. import exceptions as pg_exc
from . import element3 as element

from hashlib import md5
from ..resolved.crypt import crypt

Receiving = True
Sending = False
Complete = (None, None)

AsynchronousMap = {
	element.Notice.type : element.Notice.parse,
	element.Notify.type : element.Notify.parse,
	element.ShowOption.type : element.ShowOption.parse,
}

def return_arg(x):
	return x

class Transaction(object, metaclass = ABCMeta):
	"""
	If the fatal attribute is not None, an error occurred, and the
	`error_message` attribute should be set to a element3.Error instance.
	"""
	fatal = None

	@abstractmethod
	def messages_received(self):
		"""
		Return an iterable to the messages received that have been processed.
		"""

class Closing(Transaction):
	"""
	Send the disconnect message and mark the connection as closed.
	"""
	error_message = element.ClientError(
		# pg_exc.ConnectionDoesNotExistError.code
		code = '08003',
		severity = 'FATAL',
		message = 'operation on closed connection',
		hint = "A new connection needs to be "\
			"created in order to query the server.",
	)

	def messages_received(self):
		return ()

	def sent(self):
		"""
		Empty messages and mark complete.
		"""
		self.messages = ()
		self.fatal = True
		self.state = Complete

	def __init__(self):
		self.messages = (element.DisconnectMessage,)
		self.state = (Sending, self.sent)

class Negotiation(Transaction):
	"""
	Negotiation is a protocol transaction used to manage the initial stage of a
	connection to PostgreSQL.

	This transaction revolves around the `state_machine` method which is a
	generator that takes individual messages and progresses the state of the
	connection negotiation. This was chosen over the route taken by
	`Transaction`, seen later, as it's not terribly performance intensive and
	there are many conditions which make a generator ideal for managing the
	state.
	"""
	state = None

	def __init__(self,
		startup_message : "startup message to send",
		password : "password source data(encoded password bytes)",
	):
		self.startup_message = startup_message
		self.password = password
		self.received = [()]
		self.asyncs = []
		self.authtype = None
		self.killinfo = None
		self.authok = None
		self.last_ready = None
		self.machine = self.state_machine()
		self.messages = next(self.machine)
		self.state = (Sending, self.sent)

	def __repr__(self):
		s = type(self).__module__ + "." + type(self).__name__
		s += pformat((self.startup_message, self.password)).lstrip()
		return s

	def messages_received(self):
		return self.processed

	def sent(self):
		"""
		Empty messages and switch state to receiving.

		This is called by the user after the `messages` have been sent to the
		remote end. That is, this merely finalizes the "Sending" state.
		"""
		self.messages = ()
		self.state = (Receiving, self.put_messages)

	def put_messages(self, messages):
		# Record everything received.
		out_messages = ()
		if messages is not self.received[-1]:
			self.received.append(messages)
		else:
			raise RuntimeError("negotiation was interrupted")

		# if an Error message was found, complete and leave.
		count = 0
		try:
			for x in messages:
				count += 1
				if x[0] is element.Error.type:
					if self.fatal is None:
						self.error_message = element.Error.parse(x[1])
						self.fatal = True
						self.state = Complete
						return count
				elif x[0] in AsynchronousMap:
					self.asyncs.append(
						AsynchronousMap[x[0]](x[1])
					)
				else:
					out_messages = self.machine.send(x)
					if out_messages:
						break
		except StopIteration:
			# generator is complete, negotiation is complete..
			self.state = Complete
			return count

		if out_messages:
			self.messages = out_messages
			self.state = (Sending, self.sent)
		return count

	def unsupported_auth_request(self, req):
		self.fatal = True
		self.error_message = element.ClientError(
			"unsupported authentication request %r(%d)" %(
				element.AuthNameMap.get(req, '<unknown>'), req,
			),
			code = "--AUT",
			hint = \
				"'postgresql.protocol' only supports: " \
				"MD5, crypt, plaintext, and trust."
		)
		self.state = Complete

	def state_machine(self):
		"""
		Generator keeping the state of the connection negotiation process.
		"""
		x = (yield (self.startup_message,))

		if x[0] is not element.Authentication.type:
			self.fatal = True
			self.error_message = element.ClientError(
				message = \
					"received message of type %s, " \
					"but expected %s" %(
						repr(x[0]),
						repr(element.Authentication.type)
					),
				code = '08P01',
			)
			return

		self.authtype = element.Authentication.parse(x[1])

		req = self.authtype.request
		if req != element.AuthRequest_OK:
			if req == element.AuthRequest_Cleartext:
				pw = self.password
			elif req == element.AuthRequest_Crypt:
				pw = crypt(self.password, self.authtype.salt)
			elif req == element.AuthRequest_MD5:
				pw = md5(self.password + self.startup_message[b'user']).hexdigest().encode('ascii')
				pw = b'md5' + md5(pw + self.authtype.salt).hexdigest().encode('ascii')
			else:
				##
				# Not going to work. Sorry :(
				# The many authentication types supported by PostgreSQL are not
				# easy to implement, especially when implementations for the
				# type don't exist for Python.
				self.unsupported_auth_request(req)
				return
			x = (yield (element.Password(pw),))

			self.authok = element.Authentication.parse(x[1])
			if self.authok.request != element.AuthRequest_OK:
				self.fatal = True
				self.error_message = element.ClientError(
					message = \
						"expected an OK from the authentication " \
						"message, but received %s(%s) instead" %(
							repr(element.AuthNameMap.get(
								self.authok.request, '<unknown>'
							)),
							repr(self.authok.request),
						),
					code = "08P01"
				)
				return
		else:	
			self.authok = self.authtype

		# Done authenticating, pick up the killinfo and the ready message.
		x = (yield None)
		if x[0] is not element.KillInformation.type:
			self.fatal = True
			self.error_message = element.ClientError(
				message = \
					"received message of type %s, " \
					"but expected %s" %(
						repr(x[0]),
						element.KillInformation.type
					),
				code = "08P01"
			)
			return
		self.killinfo = element.KillInformation.parse(x[1])

		x = (yield None)
		if x[0] is not element.Ready.type:
			self.fatal = True
			self.error_message = element.ClientError(
				message = \
					"received message of type %s, " \
					"but expected %s" %(
						repr(x[0]),
						repr(element.Ready.type)
					),
				code = "08P01"
			)
			return
		self.last_ready = element.Ready.parse(x[1])

class Instruction(Transaction):
	"""
	Manage the state of a sequence of request messages to be sent to the server.
	It provides the messages to be sent and takes the response messages for order
	and integrity validation:

		Instruction([.element3.Message(), ..])

	A message must be one of:

		* `.element3.Query`
		* `.element3.Function`
		* `.element3.Parse`
		* `.element3.Bind`
		* `.element3.Describe`
		* `.element3.Close`
		* `.element3.Execute`
		* `.element3.Synchronize`
		* `.element3.Flush`
	"""
	state = None
	CopyFailMessage = element.CopyFail(b"invalid termination")

	# The hook is the dictionary that provides the path for the
	# current working message. The received messages ultimately come
	# through here and get parsed using the associated callable.
	# Messages that complete a command are paired with None.
	hook = {
		element.Query.type : (
			# 0: Start.
			{
				element.TupleDescriptor.type : (element.TupleDescriptor.parse, 3),
				element.Null.type : (element.Null.parse, 0),
				element.Complete.type : (element.Complete.parse, 0),
				element.CopyToBegin.type : (element.CopyToBegin.parse, 2),
				element.CopyFromBegin.type : (element.CopyFromBegin.parse, 1),
				element.Ready.type : (element.Ready.parse, None),
			},
			# 1: Complete.
			{
				element.Complete.type : (element.Complete.parse, 0),
			},
			# 2: Copy Data.
			# CopyData until CopyDone.
			# Complete comes next.
			{
				element.CopyData.type : (return_arg, 2),
				element.CopyDone.type : (element.CopyDone.parse, 1),
			},
			# 3: Row Data.
			{
				element.Tuple.type : (element.Tuple.parse, 3),
				element.Complete.type : (element.Complete.parse, 0),
				element.Ready.type : (element.Ready.parse, None),
			},
		),

		element.Function.type : (
			{element.FunctionResult.type : (element.FunctionResult.parse, 1)},
			{element.Ready.type : (element.Ready.parse, None)},
		),

		# Extended Protocol
		element.Parse.type : (
			{element.ParseComplete.type : (element.ParseComplete.parse, None)},
		),

		element.Bind.type : (
			{element.BindComplete.type : (element.BindComplete.parse, None)},
		),

		element.Describe.type : (
			# Still needs the descriptor.
			{
				element.AttributeTypes.type : (element.AttributeTypes.parse, 1),
				element.TupleDescriptor.type : (
					element.TupleDescriptor.parse, None
				),
			},
			# NoData or TupleDescriptor
			{
				element.NoData.type : (element.NoData.parse, None),
				element.TupleDescriptor.type : (
					 element.TupleDescriptor.parse, None
				),
			},
		),

		element.Close.type : (
			{element.CloseComplete.type : (element.CloseComplete.parse, None)},
		),

		element.Execute.type : (
			# 0: Start.
			{
				element.Tuple.type : (element.Tuple.parse, 1),
				element.CopyToBegin.type : (element.CopyToBegin.parse, 2),
				element.CopyFromBegin.type : (element.CopyFromBegin.parse, 3),
				element.Null.type : (element.Null.parse, None),
				element.Complete.type : (element.Complete.parse, None),
			},
			# 1: Row Data.
			{
				element.Tuple.type : (element.Tuple.parse, 1),
				element.Suspension.type : (element.Suspension.parse, None),
				element.Complete.type : (element.Complete.parse, None),
			},
			# 2: Copy Data.
			{
				element.CopyData.type : (return_arg, 2),
				element.CopyDone.type : (element.CopyDone.parse, 3),
			},
			# 3: Complete.
			{
				element.Complete.type : (element.Complete.parse, None),
			},
		),

		element.Synchronize.type : (
			{element.Ready.type : (element.Ready.parse, None)},
		),

		element.Flush.type : None,
	}

	initial_state = (
		(),     # last messages,
		(0, 0), # request position, response position
		(0, 0), # last request position, last response position
	)

	def __init__(self, commands, asynchook = return_arg):
		"""
		Initialize an `Instruction` instance using the given commands.

		Commands are `postgresql.protocol.element3.Message` instances:

		 * `.element3.Query`
		 * `.element3.Function`
		 * `.element3.Parse`
		 * `.element3.Bind`
		 * `.element3.Describe`
		 * `.element3.Close`
		 * `.element3.Execute`
		 * `.element3.Synchronize`
		 * `.element3.Flush`
		"""
		# Commands are accessed by index.
		self.commands = tuple(commands)
		self.asynchook = asynchook
		self.completed = []
		self.last = self.initial_state
		self.messages = list(self.commands)
		self.state = (Sending, self.standard_sent)
		self.fatal = None

		for cmd in self.commands:
			if cmd.type not in self.hook:
				raise TypeError(
					"unknown message type for PQ 3.0 protocol", cmd.type
				)

	def __repr__(self):
		return '%s.%s(%s%s)' %(
			type(self).__module__,
			type(self).__name__,
			os.linesep,
			pformat(self.commands)
		)

	def messages_received(self):
		'Received and validate messages'
		return chain.from_iterable(map(get1, self.completed))

	def reverse(self):
		"""
		A iterator that producing the completed messages in reverse
		order. Last in, first out.
		"""
		return chain.from_iterable(
			map(
				compose((get1, reversed)),
				reversed(self.completed)
			)
		)

	def standard_put(self, messages):
		"""
		Attempt to forward the state of the transaction using the given
		messages. "put" messages into the transaction for processing.

		If an invalid command is initialized on the `Transaction` object, an
		`IndexError` will be thrown.
		"""
		# We processed it, but apparently something went wrong,
		# so go ahead and reprocess it.
		if messages is self.last[0]:
			offset, current_step = self.last[1]
			# don't clear the asyncs. they have already been process by the hook.
		else:
			offset, current_step = self.last[2]
			# it's a new set, so we can clear the asyncs record.
			self._asyncs = []
		cmd = self.commands[offset]
		paths = self.hook[cmd.type]
		processed = []
		count = 0

		for x in messages:
			count += 1
			# For the current message, get the path for the message
			# and whether it signals the end of the current command
			path, next_step = paths[current_step].get(x[0], (None, None))

			if path is None:
				# No path for message type, could be a protocol error.
				if x[0] is element.Error.type:
					em = element.Error.parse(x[1])
					fatal = em['severity'].upper() in (b'FATAL', b'PANIC')
					self.error_message = em
					self.fatal = fatal
					if fatal is True:
						# can't sync up if it's fatal.
						self.state = Complete
						return count
					# Error occurred, so sync up with backend if
					# the current command is not 'Q' or 'F' as they
					# imply a sync message.
					if cmd.type not in (
						element.Function.type, element.Query.type
					):
						for offset in range(offset, len(self.commands)):
							if self.commands[offset] is element.SynchronizeMessage:
								break
						else:
							##
							# It's done.
							self.state = Complete
							return count
					##
					# Not quite done, the state(Ready) message still
					# needs to be received.
					cmd = self.commands[offset]
					paths = self.hook[cmd.type]
					# On a new command, setup the new step.
					current_step = 0
					continue
				elif x[0] in AsynchronousMap:
					if x not in self._asyncs:
						msg = AsynchronousMap[x[0]](x[1])
						try:
							self.asynchook(msg)
						except Exception as err:
							# exception thrown by async message handler?
							# notify the user, but continue...
							sys.excepthook(*sys.exc_info())
						# it's been processed, so don't process it again.
						self._asyncs.append(x)
				else:
					##
					# Procotol violation.
					self.error_message = element.ClientError(
						"expected message of types %r, " \
						"but received %r instead" % (
							tuple(paths[current_step].keys()), x[0]
						),
						code = '08P01',
						severity = 'FATAL',
					)
					self.fatal = True
					self.state = Complete
					return count
			else:
				# Valid message
				r = path(x[1])
				processed.append(r)

				if next_step is not None:
					current_step = next_step
				else:
					current_step = 0
					if r.type is element.Ready.type:
						self.last_ready = r.xact_state
					# Done with the current command. Increment the offset, and
					# try to process the new command with the remaining data.
					paths = None
					while paths is None:
						# Increment the offset past any commands
						# whose hook is None (FlushMessage)
						offset += 1
						# If the offset is the length,
						# the transaction is complete.
						if offset == len(self.commands):
							# Done with transaction.
							break
						cmd = self.commands[offset]
						paths = self.hook[cmd.type]
					else:
						# More commands to process in this transaction.
						continue
					# The while loop was broken offset == len(self.commands)
					# So, that's all there is to this transaction.
					break

		# Push the messages onto the completed list if they
		# have not been put there already.
		if not self.completed or self.completed[-1][0] != id(messages):
			self.completed.append((id(messages), processed))

		# Store the state for the next transition.
		self.last = (messages, self.last[2], (offset, current_step),)

		if offset == len(self.commands):
			# transaction complete.
			self.state = Complete
		elif cmd.type in (element.Execute.type, element.Query.type) and \
		processed:
			# Check the context to identify if the state should be
			# switched to an optimized processor.
			last = processed[-1]
			if type(last) is bytes:
				self.state = (Receiving, self.put_copydata)
			elif last.type is element.CopyToBegin.type:
				self.state = (Receiving, self.put_copydata)
			elif last.type is element.Tuple.type:
				self.state = (Receiving, self.put_tupledata)
			elif last.type is element.CopyFromBegin.type:
				self.CopyFailSequence = (self.CopyFailMessage,) + \
					self.commands[offset+1:]
				self.CopyDoneSequence = (element.CopyDoneMessage,) + \
					self.commands[offset+1:]
				self.state = (Sending, self.sent_from_stdin)
		return count

	def put_copydata(self, messages):
		"""
		In the context of a copy, `put_copydata` is used as a fast path for
		storing `element.CopyData` messages. When a non-`element.CopyData.type`
		message is received, it reverts the ``state`` attribute back to
		`standard_put` to process the message-sequence.
		"""
		# "Fail" quickly if the last message is not copy data.
		if messages[-1][0] is not element.CopyData.type:
			self.state = (Receiving, self.standard_put)
			return self.standard_put(messages)

		cdt = element.CopyData.type
		lines = [x[1] for x in messages if x[0] is cdt]
		if len(lines) != len(messages):
			self.state = (Receiving, self.standard_put)
			return self.standard_put(messages)

		if not self.completed or self.completed[-1][0] != id(messages):
			self.completed.append((id(messages), lines))
		self.last = (messages, self.last[2], self.last[2],)
		return len(messages)

	def put_tupledata(self, messages):
		"""
		Fast path used when inside an Execute command. As soon as tuple
		data is seen.
		"""
		# Fallback to `standard_put` quickly if the last
		# message is not tuple data.
		if messages[-1][0] is not element.Tuple.type:
			self.state = (Receiving, self.standard_put)
			return self.standard_put(messages)

		p = element.Tuple.parse
		t = element.Tuple.type
		tuplemessages = [p(x[1]) for x in messages if x[0] is t]
		if len(tuplemessages) != len(messages):
			self.state = (Receiving, self.standard_put)
			return self.standard_put(messages)

		if not self.completed or self.completed[-1][0] != id(messages):
			self.completed.append(((id(messages), tuplemessages)))
		self.last = (messages, self.last[2], self.last[2],)
		return len(messages)

	def standard_sent(self):
		"""
		Empty messages and switch state to receiving.

		This is called by the user after the `messages` have been sent to the
		remote end. That is, this merely finalizes the "Sending" state.
		"""
		self.messages = ()
		self.state = (Receiving, self.standard_put)
	sent = standard_sent

	def sent_from_stdin(self):
		"""
		The state method for sending copy data.

		After each call to `sent_from_stdin`, the `messages` attribute is set
		to a `CopyFailSequence`. This sequence of messages assures that the
		COPY will be properly terminated.

		If new copy data is not provided, or `messages` is *not* set to
		`CopyDoneSequence`, the transaction will instruct the remote end to
		cause the COPY to fail.
		"""
		if self.messages is self.CopyDoneSequence or \
		self.messages is self.CopyFailSequence:
			# If the last sent `messages` is CopyDone or CopyFail, finish out the
			# transaction.
			##
			self.messages = ()
			self.state = (Receiving, self.standard_put)
		else:
			##
			# Initialize to CopyFail, if the messages attribute is not
			# set properly before each invocation, the transaction is
			# being misused and will be terminated.
			self.messages = self.CopyFailSequence
