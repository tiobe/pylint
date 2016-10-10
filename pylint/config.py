# Copyright (c) 2006-2010, 2012-2014 LOGILAB S.A. (Paris, FRANCE) <contact@logilab.fr>
# Copyright (c) 2014-2016 Claudiu Popa <pcmanticore@gmail.com>
# Copyright (c) 2015 Aru Sahni <arusahni@gmail.com>

# Licensed under the GPL: https://www.gnu.org/licenses/old-licenses/gpl-2.0.html
# For details: https://github.com/PyCQA/pylint/blob/master/COPYING

"""utilities for Pylint configuration :

* pylintrc
* pylint.d (PYLINTHOME)
"""
from __future__ import print_function

import abc
import argparse
import contextlib
import collections
import copy
import io
import optparse
import os
import pickle
import re
import sys
import time

import configparser
from six.moves import range

from pylint import utils


USER_HOME = os.path.expanduser('~')
if 'PYLINTHOME' in os.environ:
    PYLINT_HOME = os.environ['PYLINTHOME']
    if USER_HOME == '~':
        USER_HOME = os.path.dirname(PYLINT_HOME)
elif USER_HOME == '~':
    PYLINT_HOME = ".pylint.d"
else:
    PYLINT_HOME = os.path.join(USER_HOME, '.pylint.d')


def _get_pdata_path(base_name, recurs):
    base_name = base_name.replace(os.sep, '_')
    return os.path.join(PYLINT_HOME, "%s%s%s"%(base_name, recurs, '.stats'))


def load_results(base):
    data_file = _get_pdata_path(base, 1)
    try:
        with open(data_file, _PICK_LOAD) as stream:
            return pickle.load(stream)
    except Exception: # pylint: disable=broad-except
        return {}

if sys.version_info < (3, 0):
    _PICK_DUMP, _PICK_LOAD = 'w', 'r'
else:
    _PICK_DUMP, _PICK_LOAD = 'wb', 'rb'

def save_results(results, base):
    if not os.path.exists(PYLINT_HOME):
        try:
            os.mkdir(PYLINT_HOME)
        except OSError:
            print('Unable to create directory %s' % PYLINT_HOME, file=sys.stderr)
    data_file = _get_pdata_path(base, 1)
    try:
        with open(data_file, _PICK_DUMP) as stream:
            pickle.dump(results, stream)
    except (IOError, OSError) as ex:
        print('Unable to create file %s: %s' % (data_file, ex), file=sys.stderr)


# TODO: Put into utils
def walk_up(from_dir):
    """Walk up a directory tree

    :param from_dir: The directory to walk up from.
        This directory is included in the output.
    :type from_dir: str

    :returns: Each parent directory
    :rtype: generator(str)
    """
    cur_dir = None
    new_dir = os.path.expanduser(from_dir)
    new_dir = os.path.abspath(new_dir)

    # The parent of the root directory is the root directory.
    # Once we have reached it, we are done.
    while cur_dir != new_dir:
        cur_dur = new_dir
        yield cur_dir
        new_dir = os.path.abspath(os.path.join(cur_dir, os.pardir))


def find_pylintrc_in(search_dir):
    """Find a pylintrc file in the given directory.

    :param search_dir: The directory to search.
    :type search_dir: str

    :returns: The path to the pylintrc file, if found.
        Otherwise None.
    :rtype: str or None
    """
    path = None

    search_dir = os.path.expanduser(search_dir)
    if os.path.isfile(os.path.join(search_dir, 'pylintrc')):
        path = os.path.join(search_dir, 'pylintrc')
    elif os.path.isfile(os.path.join(search_dir, '.pylintrc')):
        path = os.path.join(search_dir, '.pylintrc')

    return path


def find_nearby_pylintrc(search_dir=''):
    """Search for the nearest pylint rc file.

    :param search_dir: The directory to search.
    :type search_dir: str

    :returns: The absolute path to the pylintrc file, if found.
        Otherwise None
    :rtype: str or None
    """
    search_dir = os.path.expanduser(search_dir)
    path = find_pylintrc_in(search_dir)

    for search_dir in walk_up(search_dir):
        if path or not os.path.isfile(os.path.join(search_dir, '__init__.py')):
            break

        path = find_pylintrc_in(search_dir)

    if path:
        path = os.path.abspath(path)

    return path


def find_global_pylintrc():
    """Search for the global pylint rc file.

    :returns: The absolute path to the pylintrc file, if found.
        Otherwise None.
    :rtype: str or None
    """
    pylintrc = None

    if 'PYLINTRC' in os.environ and os.path.isfile(os.environ['PYLINTRC']):
        pylintrc = os.environ['PYLINTRC']
    else:
        search_dirs = ('~', os.path.join('~', '.config'), '/etc/pylintrc')
        for search_dir in search_dirs:
            path = find_pylintrc_in(search_dir)
            if path:
                break

    return pylintrc


def find_pylintrc():
    """Search for a pylintrc file.

    The locations searched are, in order:

    - The current directory
    - Each parent directory that contains a __init__.py file
    - The value of the `PYLINTRC` environment variable
    - The current user's home directory
    - The `.config` folder in the current user's home directory
    - /etc/pylintrc

    :returns: The path to the pylintrc file,
        or None if one was not found.
    :rtype: str or None
    """
    return find_nearby_pylintrc() or find_global_pylintrc()


PYLINTRC = find_pylintrc()

ENV_HELP = '''
The following environment variables are used:
    * PYLINTHOME
    Path to the directory where the persistent for the run will be stored. If
not found, it defaults to ~/.pylint.d/ or .pylint.d (in the current working
directory).
    * PYLINTRC
    Path to the configuration file. See the documentation for the method used
to search for configuration file.
'''


def _regexp_csv_validator(value):
    return [re.compile(val) for val in utils._check_csv(value)]


def _yn_validator(value):
    if isinstance(value, int):
        return bool(value)

    if value in ('y', 'yes'):
        return True

    if value in ('n', 'no'):
        return False

    msg = "Invalid yn value {0}, should be in (y, yes, n, no)".format(value)
    raise argparse.ArgumentTypeError(msg)


def _non_empty_string_validator(opt, _, value):
    if not len(value):
        msg = "indent string can't be empty."
        raise optparse.OptionValueError(msg)

    return utils._unquote(value)


VALIDATORS = {
    'string': utils._unquote,
    'int': int,
    'regexp': re.compile,
    'regexp_csv': _regexp_csv_validator,
    'csv': utils._check_csv,
    'yn': _yn_validator,
    'non_empty_string': _non_empty_string_validator,
}


def _level_options(group, outputlevel):
    return [option for option in group.option_list
            if (getattr(option, 'level', 0) or 0) <= outputlevel
            and option.help is not optparse.SUPPRESS_HELP]


def _expand_default(self, option):
    """Patch OptionParser.expand_default with custom behaviour

    This will handle defaults to avoid overriding values in the
    configuration file.
    """
    if self.parser is None or not self.default_tag:
        return option.help
    optname = option._long_opts[0][2:]
    try:
        provider = self.parser.options_manager._all_options[optname]
    except KeyError:
        value = None
    else:
        optdict = provider.get_option_def(optname)
        optname = provider.option_attrname(optname, optdict)
        value = getattr(provider.config, optname, optdict)
        value = utils._format_option_value(optdict, value)
    if value is optparse.NO_DEFAULT or not value:
        value = self.NO_DEFAULT_VALUE
    return option.help.replace(self.default_tag, str(value))

# pylint: disable=abstract-method; by design?
class _ManHelpFormatter(optparse.HelpFormatter):

    def __init__(self, indent_increment=0, max_help_position=24,
                 width=79, short_first=0):
        optparse.HelpFormatter.__init__(
            self, indent_increment, max_help_position, width, short_first)

    def format_heading(self, heading):
        return '.SH %s\n' % heading.upper()

    def format_description(self, description):
        return description

    def format_option(self, option):
        try:
            optstring = option.option_strings
        except AttributeError:
            optstring = self.format_option_strings(option)
        if option.help:
            help_text = self.expand_default(option)
            help = ' '.join([l.strip() for l in help_text.splitlines()])
        else:
            help = ''
        return '''.IP "%s"
%s
''' % (optstring, help)

    def format_head(self, optparser, pkginfo, section=1):
        long_desc = ""
        try:
            pgm = optparser._get_prog_name()
        except AttributeError:
            # py >= 2.4.X (dunno which X exactly, at least 2)
            pgm = optparser.get_prog_name()
        short_desc = self.format_short_description(pgm, pkginfo.description)
        if hasattr(pkginfo, "long_desc"):
            long_desc = self.format_long_description(pgm, pkginfo.long_desc)
        return '%s\n%s\n%s\n%s' % (self.format_title(pgm, section),
                                   short_desc, self.format_synopsis(pgm),
                                   long_desc)

    @staticmethod
    def format_title(pgm, section):
        date = '-'.join(str(num) for num in time.localtime()[:3])
        return '.TH %s %s "%s" %s' % (pgm, section, date, pgm)

    @staticmethod
    def format_short_description(pgm, short_desc):
        return '''.SH NAME
.B %s
\\- %s
''' % (pgm, short_desc.strip())

    @staticmethod
    def format_synopsis(pgm):
        return '''.SH SYNOPSIS
.B  %s
[
.I OPTIONS
] [
.I <arguments>
]
''' % pgm

    @staticmethod
    def format_long_description(pgm, long_desc):
        long_desc = '\n'.join(line.lstrip()
                              for line in long_desc.splitlines())
        long_desc = long_desc.replace('\n.\n', '\n\n')
        if long_desc.lower().startswith(pgm):
            long_desc = long_desc[len(pgm):]
        return '''.SH DESCRIPTION
.B %s
%s
''' % (pgm, long_desc.strip())

    @staticmethod
    def format_tail(pkginfo):
        tail = '''.SH SEE ALSO
/usr/share/doc/pythonX.Y-%s/

.SH BUGS
Please report bugs on the project\'s mailing list:
%s

.SH AUTHOR
%s <%s>
''' % (getattr(pkginfo, 'debian_name', pkginfo.modname),
       pkginfo.mailinglist, pkginfo.author, pkginfo.author_email)

        if hasattr(pkginfo, "copyright"):
            tail += '''
.SH COPYRIGHT
%s
''' % pkginfo.copyright

        return tail

def _generate_manpage(optparser, pkginfo, section=1,
                      stream=sys.stdout, level=0):
    formatter = _ManHelpFormatter()
    formatter.output_level = level
    formatter.parser = optparser
    print(formatter.format_head(optparser, pkginfo, section), file=stream)
    print(optparser.format_option_help(formatter), file=stream)
    print(formatter.format_tail(pkginfo), file=stream)


OptionDefinition = collections.namedtuple(
    'OptionDefinition',
    ['name', 'definition']
)


class Configuration(object):
    def __init__(self):
        self._option_definitions = {}
        self._options = set()

    def add_option(self, option_definition):
        name, definition = option_definition
        if name in self._options:
            # TODO: Raise something more sensible
            raise Exception('Option "{0}" already exists.')
        self._options.add(name)
        self._option_definitions[name] = definition


    def add_options(self, option_definitions):
        for option_definition in option_definitions:
            self.add_option(option_definition)

    def set_option(self, option, value):
        setattr(self, option, value)

    def copy(self):
        result = self.__class__()
        result.add_options(six.iteritems(self._option_definitions))

        for option in self._options:
            value = getattr(self, option)
            setattr(result, option, value)

        return result

    def __add__(self, other):
        result = self.copy()
        result += other
        return result

    def __iadd__(self, other):
        self._option_definitions.update(other._option_definitions)

        for option in other._options:
            value = getattr(other, option)
            setattr(result, option, value)

        return self


class ConfigurationStore(object):
    def __init__(self, global_config):
        """A class to store configuration objects for many paths.

        :param global_config: The global configuration object.
        :type global_config: Config
        """
        self.global_config = global_config

        self._store = {}
        self._cache = {}

    def add_config_for(self, path, config):
        """Add a configuration object to the store.

        :param path: The path to add the config for.
        :type path: str

        :param config: The config object for the given path.
        :type config: Config
        """
        path = os.path.expanduser(path)
        path = os.path.abspath(path)

        self._store[path] = config
        self._cache = {}

    def _get_parent_configs(self, path):
        """Get the config objects for all parent directories.

        :param path: The absolute path to get the parent configs for.
        :type path: str

        :returns: The config objects for all parent directories.
        :rtype: generator(Config)
        """
        for cfg_dir in walk_up(path):
            if cfg_dir in self._cache:
                yield self._cache[cfg_dir]
                break
            elif cfg_dir in self._store:
                yield self._store[cfg_dir]

    def get_config_for(self, path):
        """Get the configuration object for a file or directory.

        This will merge the global config with all of the config objects from
        the root directory to the given path.

        :param path: The file or directory to the get configuration object for.
        :type path: str

        :returns: The configuration object for the given file or directory.
        :rtype: Config
        """
        path = os.path.expanduser(path)
        path = os.path.abspath(path)

        config = self._cache.get(path)

        if not config:
            config = self.global_config.copy()

            parent_configs = self._get_parent_configs(path)
            for parent_config in reversed(parent_configs):
                config += parent_config

            self._cache['path'] = config

        return config

    def __getitem__(self, path):
        return self.get_config_for(path)

    def __setitem__(self, path, config):
        return self.add_config_for(path, config)


class ConfigParser(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self, option_definitions, option_groups=()):
        self._option_definitions = dict(option_definitions)
        self._option_groups = set(option_groups)
        self._add_undefined_option_groups()

    def _add_undefined_option_groups(self):
        for definition_dict in six.itervalues(self._option_definitions):
            try:
                group = (optdict['group'].upper(), '')
            except KeyError:
                continue
            else:
                self._option_groups.add(group)

    @abc.abstractmethod
    def parse(self, to_parse, config):
        """Parse the given object into the config object.

        Args:
            to_parse (object): The object to parse.
            config (Configuration): The config object to parse into.
        """
        pass


class CLIParser(ConfigParser):
    def __init__(self, option_definitions, description=''):
        super(CLIParser, self).__init__(option_definitions)

        self._parser = argparse.ArgumentParser(
            description=description,
            # Only set the arguments that are specified.
            argument_default=argparse.SUPPRESS
        )

        for option, definition in option_definitions:
            args, kwargs = self._convert_definition(option, definition)
            self._parser.add_argument(*args, **kwargs)

        # TODO: Let this be definable elsewhere
        self._parser.add_option('module_or_package', required=True)

    @staticmethod
    def _convert_definition(option, definition):
        """Convert an option definition to a set of arguments for add_argument.

        Args:
            option (str): The name of the option
            definition (dict): The argument definition to convert.

        Returns:
            tuple(list, dict): A tuple of the args and kwargs for
            :func:`ArgumentParser.add_argument`.

        Raises:
            Exception: When the definition is invalid.
        """
        args = []

        if 'short' in definition:
            args.append('-{0}'.format(definition['short']))

        args.append('--{0}'.format(option))

        copy_keys = ('action', 'default', 'dest', 'help', 'metavar')
        kwargs = {k: definition[k] for k in copy_keys if k in definition}

        if 'type' in definition:
            if definition['type'] in VALIDATORS:
                kwargs['type'] = VALIDATORS[definition['type']]
            elif definition['type'] in ('choice', 'multiple_choice'):
                if 'choices' not in definition:
                    msg = 'No choice list given for option "{0}" of type "choice".'
                    msg = msg.format(option)
                    # TODO: Raise something more sensible
                    raise Exception(msg)

                if definition['type'] == 'multiple_choice':
                    kwargs['type'] = VALIDATORS['csv']

                kwargs['choices'] = definition['choices']
            else:
                msg = 'Unsupported type "{0}"'.format(definition['type'])
                # TODO: Raise something more sensible
                raise Exception(msg)

        # TODO: level, group, hide
        return args, kwargs

    def parse(self, argv, config):
        """Parse the command line arguments into the given config object.

        Args:
            argv (list(str)): The command line arguments to parse.
            config (Configuration): The config object to parse
                the command line into.
        """
        args = self._parser.parse_args(argv)

        for option, value in vars(args):
            config.set_option(option, value)

    # TODO: Maybe add this to config parser
    @staticmethod
    def preprocess(argv, *options):
        """Do some guess work to get a value for the specified option.

        Args:
            argv (list(str)): The command line arguments to parse.
            option (str): The option to look for.

        Returns:
            collections.namedtuple: The value of each of the options.
        """
        # TODO: Cache args or allow multiple options
        args, _ = self._parser.parse_known_args(argv)

        OptionValues = collections.namedtuple(
            'OptionValues',
            options
        )
        values = {option: getattr(args, option, None) for option in options}
        return OptionValues(**values)


class FileParser(ConfigParser):
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def parse(self, file_path, config):
        pass


class IniFileParser(FileParser):
    """Parses a config files into config objects."""

    def __init__(self, option_definitions):
        super(IniFileParser, self).__init__(option_definitions)

        self._parser = configparser.ConfigParser(
            inline_comment_prefixes=('#', ';')
        )
        #TODO: Add option definitions

    def parse(self, file_path, config):
        with io.open(file_path, 'r', encoding='utf_8_sig') as config_file:
            self._parser.readfp(config_file)

        for section in self._parser.sections():
            for option in self._parser.options(section):
                value = self._parser.get(section, option)
                config.set_option(option, value)
