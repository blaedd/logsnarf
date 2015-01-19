#!/usr/bin/env python
# -*- coding: utf-8 -*-
# -*- test-case-name: logsnarf.test.test_config -*-
# pylint: disable=invalid-name
"""Logsnarf configuration.

See :doc:`configuration <configuration>` for details on how to configure
logsnarf.
"""

import collections
import logging.config
import ConfigParser
import os
import os.path

from xdg import BaseDirectory
from twisted.python import log


DEFAULTS = {
    'batchsize': '250',
    'default_tz': 'UTC',
    'flush_interval': '30',
    'max_buffer': '1000',
    'pattern': r'.*\.log',
    'schema_file': '%(__name__)s_schema.json',
    'state_file': '%(__name__)s_state.json',
    'table_name_fmt': 'logs_{YEAR}{MONTH}{DAY}',
    'recursive': 'true'
}


class ConfigSection(collections.Mapping):
    """Class representing a ConfigParser section.

    Provides a mapping interface that attempts to do some vaguely sane
    type casting. No attempt to be smart, cache results etc is done.
    """

    def __init__(self, name, cfg):
        """

        :param name: section name
        :type name: str
        :param cfg: ConfigParser object
        :type cfg: ConfigParser.ConfigParser
        """
        super(ConfigSection, self).__init__()
        self.name = name
        self.cfg = cfg

    def __getitem__(self, item):
        cfg, name = self.cfg, self.name

        for get in cfg.getboolean, cfg.getint, cfg.getfloat:
            try:
                value = get(name, item)
                return value
            except (ValueError, AttributeError):
                pass
            except ConfigParser.NoOptionError, e:
                raise ValueError(*e.args)
        return cfg.get(name, item)

    def __len__(self):
        return len(self.cfg.items(self.name))

    def __iter__(self):
        return iter(dict(self.cfg.items(self.name)))


# noinspection PyPep8Naming
class Config(collections.Mapping):
    """Class to contain configuration information for Logsnarf.

    This class wraps loading of the ConfigParser config file(s), initializing
    logging (from a logging.ini), and proxies some methods from
    xdg.BaseDirectory module for creating/opening config or data files in
    appropriate places.

    It also provides a dict-like read-only interface to the config file, with
    a vague attempt at type casting through ConfigSection objects.
    """
    # pylint: disable=too-many-public-methods

    def __init__(self, resource_name=None, config_file=None):
        """

        :param resource_name:
            The xdg resource name to use. Defaults to logsnarf
        :type resource_name: str
        :param config_file: absolute path to a configuration file
        :type config_file: str

        """
        super(Config, self).__init__()
        self.resource_name = resource_name or 'logsnarf'
        self.config_file = config_file
        self._cp = ConfigParser.SafeConfigParser(DEFAULTS)
        self._sections = {}

    def __getitem__(self, item):
        if self._cp.has_section(item):
            return self._sections.setdefault(
                item,
                ConfigSection(item, self._cp))

    def __len__(self):
        return len(self._cp.sections())

    def __iter__(self):
        return iter(self._cp.sections())

    def load(self):
        """Initializes logging and loads the configs."""
        self.loadLoggingConfig()
        self.loadConfigs()

    def loadConfigs(self):
        """Loads all configurations"""
        if self.config_file:
            self._cp.read(self.config_file)
        else:
            config_paths = reversed(
                [os.path.join(p, '{}.ini'.format(self.resource_name))
                 for p in self.loadConfigPaths()])
            self._cp.read(config_paths)

    def loadLoggingConfig(self):
        """Initializes logging.

        The twisted PythonLoggingObserver is initialized, then the config
        paths are searched for a ${RESOURCE_NAME}/logging.ini, failing that,
        logging.basicConfig() is called with no arguments so that some sort of
        logging occurs.
        """
        observer = log.PythonLoggingObserver()
        observer.start()
        for path in self.loadConfigPaths():
            if os.path.exists(os.path.join(path, 'logging.ini')):
                logging.config.fileConfig(os.path.join(path, 'logging.ini'))

                return
        logging.basicConfig()

    def openConfigFile(self, name, mode):
        """Opens a file in the user config directory, with the given mode.

        :param name: the name of the config file to open
        :type name: str
        :param mode: mode to  open file with
        :type mode: str
        :return: file object opened with the config file
        :rtype: file

        """
        return open(
            os.path.join(self.saveConfigPath(), name), mode)

    def openDataFile(self, name, mode):
        """Opens a file in the user data directory, with the given mode.

        :param name: the name of the data file to open
        :type name: str
        :param mode: mode to  open file with
        :type mode: str
        :return: file object opened with the data file
        :rtype: file

        """
        return open(
            os.path.join(self.saveDataPath(), name), mode)

    def saveConfigPath(self, name=''):
        """Ensures the user save config path exists, and returns the path.

        Optionally also provide a filename, to receive a full path to that
        file in the data directory.

        Ensure ``$XDG_CONFIG_HOME/logsnarf/`` exists, and return its path.
        Use this when saving or updating application configuration.

        :param str name: the name of the file
        :return: path to the directory, or, if given, file
        :rtype: str

        """
        if name:
            return os.path.join(
                BaseDirectory.save_config_path(self.resource_name), name)
        else:
            return BaseDirectory.save_config_path(self.resource_name)

    def saveDataPath(self, name=''):
        """Ensures the user save data path exists, and returns the path to it.

        Optionally also provide a filename, to receive a full path to that
        file in the data directory.

        Ensure ``$XDG_DATA_HOME/logsnarf/`` exists, and return its path.
        Use this when saving or updating application data.

        :param str name: the name of the file
        :return: path to the directory, or, if given, file
        :rtype: str

        """
        if name:
            return os.path.join(
                BaseDirectory.save_data_path(self.resource_name), name)
        else:
            return BaseDirectory.save_data_path(self.resource_name)

    def loadConfigPaths(self):
        """Returns the configuration paths for the resource.

        Returns an iterator which gives each directory named 'logsnarf' in the
        configuration search path. Information provided by earlier directories
        should take precedence over later ones, and the user-specific config
        dir comes first.
        """
        return BaseDirectory.load_config_paths(self.resource_name)
