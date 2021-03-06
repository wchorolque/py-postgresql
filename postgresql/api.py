##
# copyright 2009, James William Pye
# http://python.projects.postgresql.org
##
"""
Application Programmer Interface specifications for PostgreSQL (ABCs).

PG-API
======

``postgresql.api`` is a Python API for the PostgreSQL DBMS. It is designed to take
full advantage of PostgreSQL's features to provide the Python programmer with
substantial convenience.

This module is used to define PG-API. It creates a set of ABCs
that makes up the basic interfaces used to work with a PostgreSQL server.
"""
import os
import sys
import warnings
import collections
from abc import abstractproperty, abstractmethod
from operator import itemgetter

from . import sys as pg_sys
from .python.element import Element, prime_factor
from .python.doc import Doc
from .python.decorlib import propertydoc

__all__ = [
	'Message',
	'PreparedStatement',
	'Chunks',
	'Rows',
	'Cursor',
	'Connector',
	'Category',
	'Database',
	'Connection',
	'Transaction',
	'Settings',
	'StoredProcedure',
	'Driver',
	'Installation',
	'Cluster',
]

class Message(Element):
	"""
	A message emitted by PostgreSQL. This element is universal, so
	`postgresql.api.Message` is a complete implementation for representing a
	message. Any interface should produce these objects.
	"""
	_e_label = property(lambda x: getattr(x, 'details').get('severity', 'MESSAGE'))
	_e_factors = ('creator',)

	severities = (
		'DEBUG',
		'INFO',
		'NOTICE',
		'WARNING',
		'ERROR',
		'FATAL',
		'PANIC',
	)
	sources = (
		'SERVER',
		'CLIENT',
	)

	# What generated the message?
	source = 'SERVER'

	code = "00000"
	message = None
	details = None

	def __init__(self,
		message : "The primary information of the message",
		code : "Message code to attach (SQL state)" = None,
		details : "additional information associated with the message" = {},
		source : "Which side generated the message(SERVER, CLIENT)" = None,
		creator : "The interface element that called for instantiation" = None,
	):
		self.message = message
		self.details = details
		self.creator = creator
		if code is not None and self.code != code:
			self.code = code
		if source is not None and self.source != source:
			self.source = source

	def __repr__(self):
		return "{mod}.{typname}({message!r}{code}{details}{source}{creator})".format(
			mod = self.__module__,
			typname = self.__class__.__name__,
			message = self.message,
			code = (
				"" if self.code == type(self).code
				else ", code = " + repr(self.code)
			),
			details = (
				"" if not self.details
				else ", details = " + repr(self.details)
			),
			source = (
				"" if self.source is None
				else ", source = " + repr(self.source)
			),
			creator = (
				"" if self.creator is None
				else ", creator = " + repr(self.creator)
			)
		)

	@property
	def location_string(self):
		details = self.details
		loc = [
			details.get(k, '?') for k in ('file', 'line', 'function')
		]
		return (
			"" if loc == ['?', '?', '?']
			else "File {0!r}, "\
			"line {1!s}, in {2!s}".format(*loc)
		)

	# keys to filter in .details
	standard_detail_coverage = frozenset(['message', 'severity', 'file', 'function', 'line',])

	def _e_metas(self):
		yield (None, self.message)
		if self.code and self.code != "00000":
			yield ('CODE', self.code)
		locstr = self.location_string
		if locstr:
			yield ('LOCATION', locstr + ' from ' + self.source)
		else:
			yield ('LOCATION', self.source)
		for k, v in sorted(self.details.items(), key = itemgetter(0)):
			if k not in self.standard_detail_coverage:
				yield (k.upper(), str(v))

	def raise_message(self, starting_point = None):
		"""
		Take the given message object and hand it to all the primary
		factors(creator) with a msghook callable.
		"""
		if starting_point is not None:
			f = starting_point
		else:
			f = self.creator

		while f is not None:
			if getattr(f, 'msghook', None) is not None:
				if f.msghook(self):
					# the trap returned a nonzero value,
					# so don't continue raising. (like with's __exit__)
					return f
			f = prime_factor(f)
			if f:
				f = f[1]
		# if the next primary factor is without a raise or does not exist,
		# send the message to postgresql.sys.msghook
		pg_sys.msghook(self)

class Result(Element):
	"""
	A result is an object managing the results of a prepared statement.

	These objects represent a binding of parameters to a given statement object.

	For results that were constructed on the server and a reference passed back
	to the client, statement and parameters may be None.
	"""
	_e_label = 'RESULT'
	_e_factors = ('statement', 'parameters', 'cursor_id')

	@abstractmethod
	def close(self) -> None:
		"""
		Close the Result handle.
		"""

	@propertydoc
	@abstractproperty
	def cursor_id(self) -> str:
		"""
		The cursor's identifier.
		"""

	@propertydoc
	@abstractproperty
	def sql_column_types(self) -> [str]:
		"""
		The type of the columns produced by the cursor.

		A sequence of `str` objects stating the SQL type name::

			['INTEGER', 'CHARACTER VARYING', 'INTERVAL']
		"""

	@propertydoc
	@abstractproperty
	def pg_column_types(self) -> [int]:
		"""
		The type Oids of the columns produced by the cursor.

		A sequence of `int` objects stating the SQL type name::

			[27, 28]
		"""

	@propertydoc
	@abstractproperty
	def column_names(self) -> [str]:
		"""
		The attribute names of the columns produced by the cursor.

		A sequence of `str` objects stating the column name::

			['column1', 'column2', 'emp_name']
		"""

	@propertydoc
	@abstractproperty
	def column_types(self) -> [str]:
		"""
		The Python types of the columns produced by the cursor.

		A sequence of type objects::

			[<class 'int'>, <class 'str'>]
		"""

	@propertydoc
	@abstractproperty
	def parameters(self) -> (tuple, None):
		"""
		The parameters bound to the cursor. `None`, if unknown and an empty tuple
		`()`, if no parameters were given.

		These should be the *original* parameters given to the invoked statement.

		This should only be `None` when the cursor is created from an identifier,
		`postgresql.api.Database.cursor_from_id`.
		"""

	@propertydoc
	@abstractproperty
	def statement(self) -> ("PreparedStatement", None):
		"""
		The query object used to create the cursor. `None`, if unknown.

		This should only be `None` when the cursor is created from an identifier,
		`postgresql.api.Database.cursor_from_id`.
		"""

class Chunks(
	Result,
	collections.Iterator,
	collections.Iterable,
):
	pass

class Cursor(
	Result,
	collections.Iterator,
	collections.Iterable,
):
	"""
	A `Cursor` object is an interface to a sequence of tuples(rows). A result
	set. Cursors publish a file-like interface for reading tuples from a cursor
	declared on the database.

	`Cursor` objects are created by invoking the `PreparedStatement.declare`
	method or by opening a cursor using an identifier via the
	`Database.cursor_from_id` method.
	"""
	_e_label = 'CURSOR'

	_seek_whence_map = {
		0 : 'ABSOLUTE',
		1 : 'RELATIVE',
		2 : 'FROM_END',
	}
	_direction_map = {
		True : 'FORWARD',
		False : 'BACKWARD',
	}

	@abstractmethod
	def clone(self) -> "Cursor":
		"""
		Create a new cursor using the same factors as `self`.
		"""

	def __iter__(self):
		return self

	@propertydoc
	@abstractproperty
	def direction(self) -> bool:
		"""
		The default `direction` argument for read().

		When `True` reads are FORWARD.
		When `False` reads are BACKWARD.

		Cursor operation option.
		"""

	@abstractmethod
	def read(self,
		quantity : "Number of rows to read" = None,
		direction : "Direction to fetch in, defaults to `self.direction`" = None,
	) -> ["Row"]:
		"""
		Read, fetch, the specified number of rows and return them in a list.
		If quantity is `None`, all records will be fetched.

		`direction` can be used to override the default configured direction.

		This alters the cursor's position.

		Read does not directly correlate to FETCH. If zero is given as the
		quantity, an empty sequence *must* be returned.
		"""

	@abstractmethod
	def __next__(self) -> "Row":
		"""
		Get the next tuple in the cursor.
		Advances the cursor position by one.
		"""

	@abstractmethod
	def seek(self, offset, whence = 'ABSOLUTE'):
		"""
		Set the cursor's position to the given offset with respect to the
		whence parameter and the configured direction.

		Whence values:

		 ``0`` or ``"ABSOLUTE"``
		  Absolute.
		 ``1`` or ``"RELATIVE"``
		  Relative.
		 ``2`` or ``"FROM_END"``
		  Absolute from end.

		Direction effects whence. If direction is BACKWARD, ABSOLUTE positioning
		will effectively be FROM_END, RELATIVE's position will be negated, and
		FROM_END will effectively be ABSOLUTE.
		"""

class PreparedStatement(
	Element,
	collections.Callable,
	collections.Iterable,
):
	"""
	Instances of `PreparedStatement` are returned by the `prepare` method of
	`Database` instances.

	A PreparedStatement is an Iterable as well as Callable. This feature is
	supported for queries that have the default arguments filled in or take no
	arguments at all. It allows for things like:

		>>> for x in db.prepare('select * FROM table'):
		...  pass
	"""
	_e_label = 'STATEMENT'
	_e_factors = ('database', 'statement_id', 'string',)

	@propertydoc
	@abstractproperty
	def statement_id(self) -> str:
		"""
		The statment's identifier.
		"""

	@propertydoc
	@abstractproperty
	def string(self) -> object:
		"""
		The SQL string of the prepared statement.

		`None` if not available. This can happen in cases where a statement is
		prepared on the server and a reference to the statement is sent to the
		client which subsequently uses the statement via the `Database`'s
		`statement` constructor.
		"""

	@propertydoc
	@abstractproperty
	def sql_parameter_types(self) -> [str]:
		"""
		The type of the parameters required by the statement.

		A sequence of `str` objects stating the SQL type name::

			['INTEGER', 'VARCHAR', 'INTERVAL']
		"""

	@propertydoc
	@abstractproperty
	def sql_column_types(self) -> [str]:
		"""
		The type of the columns produced by the statement.

		A sequence of `str` objects stating the SQL type name::

			['INTEGER', 'VARCHAR', 'INTERVAL']
		"""

	@propertydoc
	@abstractproperty
	def pg_parameter_types(self) -> [int]:
		"""
		The type Oids of the parameters required by the statement.

		A sequence of `int` objects stating the PostgreSQL type Oid::

			[27, 28]
		"""

	@propertydoc
	@abstractproperty
	def pg_column_types(self) -> [int]:
		"""
		The type Oids of the columns produced by the statement.

		A sequence of `int` objects stating the SQL type name::

			[27, 28]
		"""

	@propertydoc
	@abstractproperty
	def column_names(self) -> [str]:
		"""
		The attribute names of the columns produced by the statement.

		A sequence of `str` objects stating the column name::

			['column1', 'column2', 'emp_name']
		"""

	@propertydoc
	@abstractproperty
	def column_types(self) -> [type]:
		"""
		The Python types of the columns produced by the statement.

		A sequence of type objects::

			[<class 'int'>, <class 'str'>]
		"""

	@propertydoc
	@abstractproperty
	def parameter_types(self) -> [type]:
		"""
		The Python types expected of parameters given to the statement.

		A sequence of type objects::

			[<class 'int'>, <class 'str'>]
		"""

	@abstractmethod
	def clone(self) -> "PreparedStatement":
		"""
		Create a new statement object using the same factors as `self`.

		When used for refreshing plans, the new clone should replace references to
		the original.
		"""

	@abstractmethod
	def __call__(self, *parameters : "Positional Parameters") -> ["Row"]:
		"""
		Execute the prepared statement with the given arguments as parameters.

		Usage:

		>>> p=db.prepare("SELECT column FROM ttable WHERE key = $1")
		>>> p('identifier')
		[...]
		"""

	@abstractmethod
	def rows(self, *parameters) -> collections.Iterable:
		"""
		Return an iterator producing rows produced by the cursor
		created from the statement bound with the given parameters.

		Row iterators are never scrollable.

		Supporting cursors will be WITH HOLD when outside of a transaction.

		`rows` is designed for the situations involving large data sets.

		Each iteration returns a single row. Arguably, best implemented:

			return itertools.chain.from_iterable(self.chunks(*parameters))
		"""

	@abstractmethod
	def chunks(self, *parameters) -> collections.Iterable:
		"""
		Return an iterator producing sequences of rows produced by the cursor
		created from the statement bound with the given parameters.

		Chunking iterators are *never* scrollable.

		Supporting cursors will be WITH HOLD when outside of a transaction.

		`chunks` is designed for the situations involving large data sets.

		Each iteration returns sequences of rows *normally* of length(seq) ==
		chunksize. If chunksize is unspecified, a default, positive integer will
		be filled in.
		"""

	@abstractmethod
	def declare(self, *parameters) -> Cursor:
		"""
		Return a scrollable cursor with hold using the statement bound with the
		given parameters.
		"""

	@abstractmethod
	def first(self, *parameters) -> "'First' object that is returned by the query":
		"""
		Execute the prepared statement with the given arguments as parameters.
		If the statement returns rows with multiple columns, return the first
		row. If the statement returns rows with a single column, return the
		first column in the first row. If the query does not return rows at all,
		return the count or `None` if no count exists in the completion message.

		Usage:

		>>> db.prepare("SELECT * FROM ttable WHERE key = $1").first("somekey")
		('somekey', 'somevalue')
		>>> db.prepare("SELECT 'foo'").first()
		'foo'
		>>> db.prepare("INSERT INTO atable (col) VALUES (1)").first()
		1
		"""

	@abstractmethod
	def load_rows(self,
		iterable : "A iterable of tuples to execute the statement with"
	):
		"""
		Given an iterable, `iterable`, feed the produced parameters to the
		query. This is a bulk-loading interface for parameterized queries.

		Effectively, it is equivalent to:

			>>> q = db.prepare(sql)
			>>> for i in iterable:
			...  q(*i)

		Its purpose is to allow the implementation to take advantage of the
		knowledge that a series of parameters are to be loaded so that the
		operation can be optimized.
		"""

	@abstractmethod
	def load_chunks(self,
		iterable : "A iterable of chunks of tuples to execute the statement with"
	):
		"""
		Given an iterable, `iterable`, feed the produced parameters of the chunks
		produced by the iterable to the query. This is a bulk-loading interface
		for parameterized queries.

		Effectively, it is equivalent to:

			>>> ps = db.prepare(...)
			>>> for c in iterable:
			...  for i in c:
			...   q(*i)

		Its purpose is to allow the implementation to take advantage of the
		knowledge that a series of chunks of parameters are to be loaded so
		that the operation can be optimized.
		"""

	@abstractmethod
	def close(self) -> None:
		"""
		Close the prepared statement releasing resources associated with it.
		"""

class StoredProcedure(
	Element,
	collections.Callable,
):
	"""
	A function stored on the database.
	"""
	_e_label = 'FUNCTION'
	_e_factors = ('database',)

	@abstractmethod
	def __call__(self, *args, **kw) -> (object, Cursor, collections.Iterable):
		"""
		Execute the procedure with the given arguments. If keyword arguments are
		passed they must be mapped to the argument whose name matches the key.
		If any positional arguments are given, they must fill in gaps created by
		the stated keyword arguments. If too few or too many arguments are
		given, a TypeError must be raised. If a keyword argument is passed where
		the procedure does not have a corresponding argument name, then,
		likewise, a TypeError must be raised.

		In the case where the `StoredProcedure` references a set returning
		function(SRF), the result *must* be an iterable. SRFs that return single
		columns *must* return an iterable of that column; not row data. If the
		SRF returns a composite(OUT parameters), it *should* return a `Cursor`.
		"""

##
# Arguably, it would be wiser to isolate blocks, prepared transactions, and
# savepoints, but the utility of the separation is not significant. It's really
# more interesting as a formality that the user may explicitly state the
# type of the transaction. However, this capability is not completely absent
# from the current interface as the configuration parameters, or lack thereof,
# help imply the expectations.
class Transaction(Element):
	"""
	A `Tranaction` is an element that represents a transaction in the session.
	Once created, it's ready to be started, and subsequently committed or
	rolled back.

	Read-only transaction:

		>>> with db.xact(mode = 'read only'):
		...  ...

	Read committed isolation:

		>>> with db.xact(isolation = 'READ COMMITTED'):
		...  ...

	Savepoints are created if inside a transaction block:

		>>> with db.xact():
		...  with db.xact():
		...   ...

	Or, in cases where two-phase commit is desired:

		>>> with db.xact(gid = 'gid') as gxact:
		...  with gxact:
		...   # phase 1 block
		...   ...
		>>> # fully committed at this point

	Considering that transactions decide what's saved and what's not saved, it is
	important that they are used properly. In most situations, when an action is
	performed where state of the transaction is unexpected, an exception should
	occur.
	"""
	_e_label = 'XACT'
	_e_factors = ('database',)

	@propertydoc
	@abstractproperty
	def mode(self) -> (None, str):
		"""
		The mode of the transaction block:

			START TRANSACTION [ISOLATION] <mode>;

		The `mode` property is a string and will be directly interpolated into the
		START TRANSACTION statement.
		"""

	@propertydoc
	@abstractproperty
	def isolation(self) -> (None, str):
		"""
		The isolation level of the transaction block:

			START TRANSACTION <isolation> [MODE];

		The `isolation` property is a string and will be directly interpolated into
		the START TRANSACTION statement.
		"""

	@propertydoc
	@abstractproperty
	def gid(self) -> (None, str):
		"""
		The global identifier of the transaction block:

			PREPARE TRANSACTION <gid>;

		The `gid` property is a string that indicates that the block is a prepared
		transaction.
		"""

	@abstractmethod
	def start(self) -> None:
		"""
		Start the transaction.

		If the database is in a transaction block, the transaction should be
		configured as a savepoint. If any transaction block configuration was
		applied to the transaction, raise a `postgresql.exceptions.OperationError`.

		If the database is not in a transaction block, start one using the
		configuration where:

		`self.isolation` specifies the ``ISOLATION LEVEL``. Normally, ``READ
		COMMITTED``, ``SERIALIZABLE``, or ``READ UNCOMMITTED``.

		`self.mode` specifies the mode of the transaction. Normally, ``READ
		ONLY`` or ``READ WRITE``.

		If the transaction is open--started or prepared, do nothing.

		If the transaction has been committed or aborted, raise an
		`postgresql.exceptions.OperationError`.
		"""
	begin = start

	@abstractmethod
	def commit(self) -> None:
		"""
		Commit the transaction.

		If the transaction is configured with a `gid` issue a COMMIT PREPARED
		statement with the configured `gid`.

		If the transaction is a block, issue a COMMIT statement.

		If the transaction was started inside a transaction block, it should be
		identified as a savepoint, and the savepoint should be released.

		If the transaction has already been committed, do nothing.
		"""

	@abstractmethod
	def rollback(self) -> None:
		"""
		Abort the transaction.

		If the transaction is configured with a `gid` *and* has been prepared, issue
		a ROLLBACK PREPARE statement with the configured `gid`.

		If the transaction is a savepoint, ROLLBACK TO the savepoint identifier.

		If the transaction is a transaction block, issue an ABORT.

		If the transaction has already been aborted, do nothing.
		"""
	abort = rollback

	@abstractmethod
	def recover(self) -> None:
		"""
		If the transaction is assigned a `gid`, recover may be used to identify
		the transaction as prepared and ready for committing or aborting.

		This method is used in recovery procedures where a prepared transaction
		needs to be committed or rolled back.

		If no prepared transaction with the configured `gid` exists, a
		`postgresql.exceptions.UndefinedObjectError` must be raised.
		[This is consistent with the error raised by ROLLBACK/COMMIT PREPARED]

		Once this method has been ran, it should identify the transaction as being
		prepared so that subsequent invocations to `commit` or `rollback` should
		cause the appropriate ROLLBACK PREPARED or COMMIT PREPARED statements to
		be executed.
		"""

	@abstractmethod
	def prepare(self) -> None:
		"""
		Explicitly prepare the transaction with the configured `gid` by issuing a
		PREPARE TRANSACTION statement with the configured `gid`.
		This *must* be called for the first phase of the commit.

		If the transaction is already prepared, do nothing.
		"""

	@abstractmethod
	def __enter__(self):
		"""
		Run the `start` method and return self.
		"""

	def __context__(self):
		'Return self.'
		return self

	@abstractmethod
	def __exit__(self, typ, obj, tb):
		"""
		If an exception is indicated by the parameters, run the transaction's
		`rollback` method iff the database is still available(not closed), and
		return a `False` value.

		If an exception is not indicated, but the database's transaction state is
		in error, run the transaction's `rollback` method and raise a
		`postgresql.exceptions.InFailedTransactionError`. If the database is
		unavailable, the `rollback` method should cause a
		`postgresql.exceptions.ConnectionDoesNotExistError` exception to occur.

		Otherwise, run the transaction's `commit` method. If the commit fails,
		a `gid` is configured, and the connection is still available, run the
		transaction's `rollback` method.

		When the `commit` is ultimately unsuccessful or not ran at all, the purpose
		of __exit__ is to resolve the error state of the database iff the
		database is available(not closed) so that more commands can be after the
		block's exit.
		"""

class Settings(
	Element,
	collections.MutableMapping
):
	"""
	A mapping interface to the session's settings. This provides a direct
	interface to ``SHOW`` or ``SET`` commands. Identifiers and values need
	not be quoted specially as the implementation must do that work for the
	user.
	"""
	_e_label = 'SETTINGS'

	@abstractmethod
	def __getitem__(self, key):
		"""
		Return the setting corresponding to the given key. The result should be
		consistent with what the ``SHOW`` command returns. If the key does not
		exist, raise a KeyError.
		"""

	@abstractmethod
	def __setitem__(self, key, value):
		"""
		Set the setting with the given key to the given value. The action should
		be consistent with the effect of the ``SET`` command.
		"""

	@abstractmethod
	def __call__(self, **kw):
		"""
		Create a context manager applying the given settings on __enter__ and
		restoring the old values on __exit__.

		>>> with db.settings(search_path = 'local,public'):
		...  ...
		"""

	@abstractmethod
	def get(self, key, default = None):
		"""
		Get the setting with the corresponding key. If the setting does not
		exist, return the `default`.
		"""

	@abstractmethod
	def getset(self, keys):
		"""
		Return a dictionary containing the key-value pairs of the requested
		settings. If *any* of the keys do not exist, a `KeyError` must be raised
		with the set of keys that did not exist.
		"""

	@abstractmethod
	def update(self, mapping):
		"""
		For each key-value pair, incur the effect of the `__setitem__` method.
		"""

	@abstractmethod
	def keys(self):
		"""
		Return an iterator to all of the settings' keys.
		"""

	@abstractmethod
	def values(self):
		"""
		Return an iterator to all of the settings' values.
		"""

	@abstractmethod
	def items(self):
		"""
		Return an iterator to all of the setting value pairs.
		"""

class Database(Element):
	"""
	The interface to an individual database. `Connection` objects inherit from
	this
	"""
	_e_label = 'DATABASE'

	@propertydoc
	@abstractproperty
	def backend_id(self) -> (int, None):
		"""
		The backend's process identifier.
		"""

	@propertydoc
	@abstractproperty
	def version_info(self) -> tuple:
		"""
		A version tuple of the database software similar Python's `sys.version_info`.

		>>> db.version_info
		(8, 1, 3, '', 0)
		"""

	@propertydoc
	@abstractproperty
	def client_address(self) -> (str, None):
		"""
		The client address that the server sees. This is obtainable by querying
		the ``pg_catalog.pg_stat_activity`` relation.

		`None` if unavailable.
		"""

	@propertydoc
	@abstractproperty
	def client_port(self) -> (int, None):
		"""
		The client port that the server sees. This is obtainable by querying
		the ``pg_catalog.pg_stat_activity`` relation.

		`None` if unavailable.
		"""

	@propertydoc
	@abstractproperty
	def xact(self,
		gid : "global identifier to configure" = None,
		isolation : "ISOLATION LEVEL to use with the transaction" = None,
		mode : "Mode of the transaction, READ ONLY or READ WRITE" = None,
	) -> Transaction:
		"""
		Create a `Transaction` object using the given keyword arguments as its
		configuration.
		"""

	@propertydoc
	@abstractproperty
	def settings(self) -> Settings:
		"""
		A `Settings` instance bound to the `Database`.
		"""

	@abstractmethod
	def execute(sql) -> None:
		"""
		Execute an arbitrary block of SQL. Always returns `None` and raise
		a `postgresql.exceptions.Error` subclass on error.
		"""

	@abstractmethod
	def prepare(self, sql : str) -> PreparedStatement:
		"""
		Create a new `PreparedStatement` instance bound to the connection
		using the given SQL.

		>>> s = db.prepare("SELECT 1")
		>>> c = s()
		>>> c.next()
		(1,)
		"""

	@abstractmethod
	def statement_from_id(self,
		statement_id : "The statement's identification string.",
	) -> PreparedStatement:
		"""
		Create a `PreparedStatement` object that was already prepared on the
		server. The distinction between this and a regular query is that it
		must be explicitly closed if it is no longer desired, and it is
		instantiated using the statement identifier as opposed to the SQL
		statement itself.
		"""

	@abstractmethod
	def cursor_from_id(self,
		cursor_id : "The cursor's identification string."
	) -> Cursor:
		"""
		Create a `Cursor` object from the given `cursor_id` that was already
		declared on the server.
		
		`Cursor` objects created this way must *not* be closed when the object
		is garbage collected. Rather, the user must explicitly close it for
		the server resources to be released. This is in contrast to `Cursor`
		objects that are created by invoking a `PreparedStatement` or a SRF
		`StoredProcedure`.
		"""

	@abstractmethod
	def proc(self,
		procedure_id : \
			"The procedure identifier; a valid ``regprocedure`` or Oid."
	) -> StoredProcedure:
		"""
		Create a `StoredProcedure` instance using the given identifier.

		The `proc_id` given can be either an ``Oid``, or a ``regprocedure``
		that identifies the stored procedure to create the interface for.

		>>> p = db.proc('version()')
		>>> p()
		'PostgreSQL 8.3.0'
		>>> qstr = "select oid from pg_proc where proname = 'generate_series'"
		>>> db.prepare(qstr).first()
		1069
		>>> generate_series = db.proc(1069)
		>>> list(generate_series(1,5))
		[1, 2, 3, 4, 5]
		"""

	@abstractmethod
	def reset(self) -> None:
		"""
		Reset the connection into it's original state.

		Issues a ``RESET ALL`` to the database. If the database supports
		removing temporary tables created in the session, then remove them.
		Reapply initial configuration settings such as path.

		The purpose behind this method is to provide a soft-reconnect method
		that re-initializes the connection into its original state. One
		obvious use of this would be in a connection pool where the connection
		is being recycled.
		"""

class SocketFactory(object):
	@propertydoc
	@abstractproperty
	def fatal_exception(self) -> Exception:
		"""
		The exception that is raised by sockets that indicate a fatal error.

		The exception can be a base exception as the `fatal_error_message` will
		indicate if that particular exception is actually fatal.
		"""

	@propertydoc
	@abstractproperty
	def timeout_exception(self) -> Exception:
		"""
		The exception raised by the socket when an operation could not be
		completed due to a configured time constraint.
		"""

	@propertydoc
	@abstractproperty
	def tryagain_exception(self) -> Exception:
		"""
		The exception raised by the socket when an operation was interrupted, but
		should be tried again.
		"""

	@propertydoc
	@abstractproperty
	def tryagain(self, err : Exception) -> bool:
		"""
		Whether or not `err` suggests the operation should be tried again.
		"""

	@abstractmethod
	def fatal_exception_message(self, err : Exception) -> (str, None):
		"""
		A function returning a string describing the failure, this string will be
		given to the `postgresql.exceptions.ConnectionFailure` instance that will
		subsequently be raised by the `Connection` object.

		Returns `None` when `err` is not actually fatal.
		"""

	@abstractmethod
	def socket_secure(self, socket : "socket object") -> "secured socket":
		"""
		Return a reference to the secured socket using the given parameters.

		If securing the socket for the connector is impossible, the user should
		never be able to instantiate the connector with parameters requesting
		security.
		"""

	@abstractmethod
	def socket_factory_sequence(self) -> [collections.Callable]:
		"""
		Return a sequence of `SocketCreator`s that `Connection` objects will use to
		create the socket object. 
		"""

class Category(Element):
	"""
	A category is an object that initializes the subject connection for a
	specific purpose.

	Arguably, a runtime class for use with connections.
	"""
	_e_label = 'CATEGORY'
	_e_factors = ()

	@abstractmethod
	def __call__(self, connection):
		"""
		Initialize the given connection in order to conform to the category.
		"""

class Connector(Element):
	"""
	A connector is an object providing the necessary information to establish a
	connection. This includes credentials, database settings, and many times
	addressing information.
	"""
	_e_label = 'CONNECTOR'
	_e_factors = ('driver', 'category')

	def __call__(self, *args, **kw):
		"""
		Create and connect. Arguments will be given to the `Connection` instance's
		`connect` method.
		"""
		return self.driver.connection(self)

	def __init__(self,
		user : "required keyword specifying the user name(str)" = None,
		password : str = None,
		database : str = None,
		settings : (dict, [(str,str)]) = None,
		category : Category = None,
	):
		if user is None:
			# sure, it's a "required" keyword, makes for better documentation
			raise TypeError("'user' is a required keyword")
		self.user = user
		self.password = password
		self.database = database
		self.settings = settings
		self.category = category
		if category is not None and not isinstance(category, Category):
			raise TypeError("'category' must a be `None` or `postgresql.api.Category`")

class Connection(Database):
	"""
	The interface to a connection to a PostgreSQL database. This is a
	`Database` interface with the additional connection management tools that
	are particular to using a remote database.
	"""
	_e_label = 'CONNECTION'
	_e_factors = ('connector',)

	@propertydoc
	@abstractproperty
	def connector(self) -> Connector:
		"""
		The `Connector` instance facilitating the `Connection` object's
		communication and initialization.
		"""

	@propertydoc
	@abstractproperty
	def closed(self) -> bool:
		"""
		`True` if the `Connection` is closed, `False` if the `Connection` is
		open.

		>>> db.closed
		True
		"""

	@abstractmethod
	def clone(self) -> "Connection":
		"""
		Create another connection using the same factors as `self`. The returned
		object should be open and ready for use.
		"""

	def connect(self) -> None:
		"""
		Establish the connection to the server and initialize the category.

		Does nothing if the connection is already established.
		"""
		cat = self.connector.category
		if cat is not None:
			cat(self)

	@abstractmethod
	def close(self) -> None:
		"""
		Close the connection.

		Does nothing if the connection is already closed.
		"""

	@abstractmethod
	def __enter__(self):
		"""
		Establish the connection and return self.
		"""

	@abstractmethod
	def __exit__(self, typ, obj, tb):
		"""
		Closes the connection and returns `False` when an exception is passed in,
		`True` when `None`.
		"""

	@abstractmethod
	def __context__(self):
		"""
		Returns the connection object, self.
		"""

class Driver(Element):
	"""
	The `Driver` element provides the `Connector` and other information
	pertaining to the implementation of the driver. Information about what the
	driver supports is available in instances.
	"""
	_e_label = "DRIVER"
	_e_factors = ()

	@abstractmethod
	def connect(**kw):
		"""
		Create a connection using the given parameters for the Connector.
		"""

class Installation(Element):
	"""
	Interface to a PostgreSQL installation. Instances would provide various
	information about an installation of PostgreSQL accessible by the Python 
	"""
	_e_label = "INSTALLATION"
	_e_factors = ('pg_config_path',)

	@propertydoc
	@abstractproperty
	def version(self):
		"""
		A version string consistent with what `SELECT version()` would output.
		"""

	@propertydoc
	@abstractproperty
	def version_info(self):
		"""
		A tuple specifying the version in a form similar to Python's
		sys.version_info. (8, 3, 3, 'final', 0)

		See `postgresql.versionstring`.
		"""

	@propertydoc
	@abstractproperty
	def type(self):
		"""
		The "type" of PostgreSQL. Normally, the first component of the string
		returned by pg_config.
		"""

	@propertydoc
	@abstractproperty
	def ssl(self) -> bool:
		"""
		Whether the installation supports SSL.
		"""

class Cluster(Element):
	"""
	Interface to a PostgreSQL cluster--a data directory. An implementation of
	this provides a means to control a server.
	"""
	_e_label = 'CLUSTER'
	_e_factors = ('installation', 'data_directory')

	@propertydoc
	@abstractproperty
	def installation(self) -> Installation:
		"""
		The installation used by the cluster.
		"""

	@propertydoc
	@abstractproperty
	def data_directory(self) -> str:
		"""
		The path to the data directory of the cluster.
		"""

	@abstractmethod
	def init(self,
		initdb : "path to the initdb to use" = None,
		user : "name of the cluster's superuser" = None,
		password : "superuser's password" = None,
		encoding : "the encoding to use for the cluster" = None,
		locale : "the locale to use for the cluster" = None,
		collate : "the collation to use for the cluster" = None,
		ctype : "the ctype to use for the cluster" = None,
		monetary : "the monetary to use for the cluster" = None,
		numeric : "the numeric to use for the cluster" = None,
		time : "the time to use for the cluster" = None,
		text_search_config : "default text search configuration" = None,
		xlogdir : "location for the transaction log directory" = None,
	):
		"""
		Create the cluster at the `data_directory` associated with the Cluster
		instance.
		"""

	@abstractmethod
	def drop(self):
		"""
		Kill the server and completely remove the data directory.
		"""

	@abstractmethod
	def start(self):
		"""
		Start the cluster.
		"""

	@abstractmethod
	def stop(self):
		"""
		Signal the server to shutdown.
		"""

	@abstractmethod
	def kill(self):
		"""
		Kill the server.
		"""

	@abstractmethod
	def restart(self):
		"""
		Restart the cluster.
		"""

	@abstractmethod
	def wait_until_started(self,
		timeout : "maximum time to wait" = 10
	):
		"""
		After the start() method is ran, the database may not be ready for use.
		This method provides a mechanism to block until the cluster is ready for
		use.

		If the `timeout` is reached, the method *must* throw a
		`postgresql.exceptions.ClusterTimeoutError`.
		"""

	@abstractmethod
	def wait_until_stopped(self,
		timeout : "maximum time to wait" = 10
	):
		"""
		After the stop() method is ran, the database may still be running.
		This method provides a mechanism to block until the cluster is completely
		shutdown.

		If the `timeout` is reached, the method *must* throw a
		`postgresql.exceptions.ClusterTimeoutError`.
		"""

	@propertydoc
	@abstractproperty
	def settings(self):
		"""
		A `Settings` interface to the ``postgresql.conf`` file associated with the
		cluster.
		"""

	@abstractmethod
	def __enter__(self):
		"""
		Start the cluster if it's not already running, and wait for it to be
		readied.
		"""

	def __context__(self):
		return self

	@abstractmethod
	def __exit__(self, exc, val, tb):
		"""
		Stop the cluster and wait for it to shutdown *iff* it was started by the
		corresponding enter.
		"""

__docformat__ = 'reStructuredText'
if __name__ == '__main__':
	help(__package__ + '.api')
##
# vim: ts=3:sw=3:noet:
