##
# copyright 2009, James William Pye
# http://python.projects.postgresql.org
##
'PQ version class'
from struct import pack, unpack

class Version(tuple):
	"""Version((major, minor)) -> Version

	Version serializer and parser.
	"""
	major = property(fget = lambda s: s[0])
	minor = property(fget = lambda s: s[1])

	def __new__(subtype, major_minor : '(major, minor)'):
		(major, minor) = major_minor
		major = int(major)
		minor = int(minor)
		# If it can't be packed like this, it's not a valid version.
		try:
			pack('!HH', major, minor)
		except Exception as e:
			raise ValueError("unpackable major and minor") from e

		return tuple.__new__(subtype, (major, minor))

	def __int__(self):
		return (self[0] << 16) | self[1]

	def bytes(self):
		return pack('!HH', self[0], self[1])

	def __repr__(self):
		return '%d.%d' %(self[0], self[1])

	def parse(self, data):
		return self(unpack('!HH', data))
	parse = classmethod(parse)

CancelRequestCode = Version((1234, 5678))
NegotiateSSLCode = Version((1234, 5679))
V2_0 = Version((2, 0))
V3_0 = Version((3, 0))
