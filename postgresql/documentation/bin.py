##
# copyright 2009, James William Pye
# http://python.projects.postgresql.org
##
r'''
Console Scripts
***************

This chapter discusses the usage of the available console scripts.


``pg_python``
=============

The ``pg_python`` command provides a simple way to write Python scripts against a
single target database. It acts like the regular Python console command, but
takes standard PostgreSQL options as well to specify the client parameters
to make establish connection with. The Python environment is then augmented
with the following built-ins:

 ``db``
  The PG-API connection object.

 ``xact``
  ``db.xact``, the transaction creator.

 ``settings``
  ``db.settings``

 ``prepare``
  ``db.prepare``, the statement creator.

 ``proc``
  ``db.proc``


pg_python Usage
---------------

Usage: pg_python.py [connection options] [script] ...

Options:
  --unix=UNIX           path to filesystem socket
  --ssl-mode=SSLMODE    SSL requirement for connectivity: require, prefer,
                        allow, disable
  -s SETTINGS, --setting=SETTINGS
                        run-time parameters to set upon connecting
  -I PQ_IRI, --iri=PQ_IRI
                        database locator string
                        [pq://user:password@host:port/database?setting=value]
  -h HOST, --host=HOST  database server host
  -p PORT, --port=PORT  database server port
  -U USER, --username=USER
                        user name to connect as
  -W, --password        prompt for password
  -d DATABASE, --database=DATABASE
                        database's name
  --pq-trace=PQ_TRACE   trace PQ protocol transmissions
  -C PYTHON_CONTEXT, --context=PYTHON_CONTEXT
                        Python context code to run[file://,module:,<code>]
  -m PYTHON_MAIN        Python module to run as script(__main__)
  -c PYTHON_MAIN        Python expression to run(__main__)
  --version             show program's version number and exit
  --help                show this help message and exit


Interactive Console Backslash Commands
--------------------------------------

Inspired by ``psql``::

	>>> \?
	Backslash Commands:

	  \?      Show this help message.
	  \E      Edit a file or a temporary script.
	  \e      Edit and Execute the file directly in the context.
	  \i      Execute a Python script within the interpreter's context.
	  \set    Configure environment variables. \set without arguments to show all
	  \x      Execute the Python command within this process.


pg_python Examples
------------------

Module execution taking advantage of the new built-ins::

	$ pg_python -h localhost -W -m timeit "prepare('SELECT 1').first()"
	Password for pg_python[pq://jwp@localhost:5432]:
	1000 loops, best of 3: 1.35 msec per loop

	$ pg_python -h localhost -W -m timeit -s "ps=prepare('SELECT 1')" "ps.first()"
	Password for pg_python[pq://jwp@localhost:5432]:
	1000 loops, best of 3: 442 usec per loop

Simple interactive usage::

	$ pg_python -h localhost -W
	Password for pg_python[pq://jwp@localhost:5432]:
	>>> ps = prepare('select 1')
	>>> ps.first()
	1
	>>> c = ps()
	>>> c.read()
	[(1,)]
	>>> ps.close()
	>>> import sys
	>>> sys.exit(0)


``pg_dotconf``
==============

pg_dotconf is used to modify a PostgreSQL cluster's configuration file.
It provides a means to apply settings specified from the command line and from a
file referenced using the ``-f`` option.

.. warning::
 ``include`` directives in configuration files are *completely* ignored. If
 modification of an included file is desired, the command must be applied to
 that specific file.


pg_dotconf Usage
----------------

Usage: pg_dotconf.py [--stdout] [-f filepath] postgresql.conf ([param=val]|[param])*

Options:
  --version             show program's version number and exit
  -h, --help            show this help message and exit
  -f SETTINGS, --file=SETTINGS
                        A file of settings to *apply* to the given
                        "postgresql.conf"
  --stdout              Redirect the product to standard output instead of
                        writing back to the "postgresql.conf" file


Examples
--------

Modifying a simple configuration file::

	$ echo "setting = value" >pg.conf
	
	# change 'setting'
	$ pg_dotconf pg.conf setting=newvalue
	
	$ cat pg.conf
	setting = 'newvalue'
	
	# new settings are appended to the file
	$ pg_dotconf pg.conf another_setting=value
	$ cat pg.conf
	setting = 'newvalue'
	another_setting = 'value'
	
	# comment a setting
	$ pg_dotconf pg.conf another_setting
	
	$ cat pg.conf
	setting = 'newvalue'
	#another_setting = 'value'

When a setting is given on the command line, it must been seen as one argument
to the command, so it's *very* important to avoid invocations like::

	$ pg_dotconf pg.conf setting = value
	ERROR: invalid setting, '=' after 'setting'
	HINT: Settings must take the form 'setting=value' or 'setting_name_to_comment'. Settings must also be received as a single argument.
'''

__docformat__ = 'reStructuredText'
if __name__ == '__main__':
	import sys
	if (sys.argv + [None])[1] == 'dump':
		sys.stdout.write(__doc__)
	else:
		try:
			help(__package__ + '.bin')
		except NameError:
			help(__name__)
