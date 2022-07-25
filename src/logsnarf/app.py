#!/usr/bin/env python
# -*- coding: utf-8 -*-
# pylint: disable=invalid-name
"""Logsnarf application.

Application code to connect the various modules to do something useful..
"""
import os
import sys
import logging
import re

from twisted.python import usage
from twisted.internet import reactor
from oauth2client.service_account import ServiceAccountCredentials
import simplejson as json

from . import config
from . import schema
from . import service
from . import snarf
from . import uploader
from . import state
from . import errors


class Options(usage.Options):
    optParameters = [
        ['resource_name', 'n', 'logsnarf', 'Resource name'],
        ['config_file', 'f', None, 'Config file'],
    ]


def install_custom_verifiers(sch, default_domain):
    # noinspection PyUnusedLocal
    def add_default_domain(unused_arg, value):
        if len(value.split('.')) == 1:
            return u'{}.{}'.format(value, default_domain)
        return unicode(value)

    def fix_pid_mess(root_obj, value):
        if value is None:
            return 0
        if isinstance(value, basestring) and '[' in value:
            pidparts = value.split('[')
            pid = int(pidparts[-1])
            pname = pidparts[0]
            root_obj['pname'] = pname
            return pid
        else:
            value = int(value)
            return value

    sch.setFieldValidator('host', add_default_domain)
    sch.setFieldValidator('src.host', add_default_domain)
    sch.setFieldValidator('dst.host', add_default_domain)
    sch.setFieldValidator('pid', fix_pid_mess)
    return sch


def install_schema_load_hook(sch):
    def loadHook(obj):
        """object_hook for JSONDecoder.

        :param obj: non-literal json decoded object
        :type obj: dict
        :return: updated object
        :rvalue: dict
        """
        fieldpath_re = re.compile(r'[.!]')
        for k in obj.copy():
            if k == 'pid' and obj[k] == '-':
                obj[k] = 0
            kparts = fieldpath_re.split(k)
            if len(kparts) > 1:
                value = obj.pop(k)
                kparts.reverse()
                entry = obj
                while len(kparts) > 1:
                    name = kparts.pop()
                    entry = entry.setdefault(name, {})
                name = kparts.pop()
                entry[name] = value
        return obj

    sch.setObjectLoadHook(loadHook)


class App(object):
    """Logsnarf application class.

    Currently this is just a convenient way to encapsulate the setup of the
    various components. It minimizes the use of the configuration object to
    make for cleaner implementation classes.

    Currently a logsnarf.App contains three main components.

    logsnarf.snarf.Logsnarf - Monitors directories for log updates, feeds them
            linewise to the next in the chain.

    logsnarf.uploader.BigQueryUploader - Receieves lines from Logsnarf,
        pushes them through the logsnarf.schema.Schema object for
        munging/verification, adds an insertId to every row, batches them into
        groups, which get a transaction id (internal use only), and passes
        them on to the BigQueryService. Partial failures (only some rows) are
        handled here. Full request failures are generally handled by the
        BigQueryService. Currently this is where flush-on-exit is handled.

    logsnarf.service.BigQueryService - Encapsulates a standard googleapi
            BigQueryService along with our project/dataset information and
            credentials.
    """

    def __init__(self, cfg, section_name):
        """

        :param cfg: config object
        :type cfg: logsnarf.config.Config
        :param section_name: section name from the config that tells us what
          to do
        :type section_name: str
        """
        self.cfg = cfg
        self.section = section = cfg[section_name]
        creds = ServiceAccountCredentials.from_p12_keyfile(
            section['service_email'],
            os.path.join(cfg.saveConfigPath(), section['keyfile']),
            scopes='https://www.googleapis.com/auth/bigquery')
        svc = service.BigQueryService(
            section['project_id'],
            section['dataset'],
            creds, debug=True)
        default_tz = section.get('default_tz', 'UTC')
        default_domain = section.get('default_domain', None)
        schema_file = cfg.openConfigFile(section['schema_file'], 'rb')
        schema_obj = schema.Schema(schema_file, default_tz)
        install_schema_load_hook(schema_obj)
        install_custom_verifiers(schema_obj, default_domain)

        table_name_fmt = section.get('table_name_fmt', None)
        upl = uploader.BigQueryUploader(schema_obj, svc, table_name_fmt)
        if 'batchsize' in section:
            upl.setBatchSize(section['batchsize'])
        if 'max_buffer' in section:
            upl.setMaxBuffer(section['max_buffer'])
        if 'flush_interval' in section:
            upl.setFlushInterval(section['flush_interval'])
        upl.setDefaultTZ(default_tz)

        state_path = cfg.saveConfigPath(section['state_file'])
        state_object = state.State(state_path)

        dirs = section.get('directories', None)
        if dirs is None:
            logging.fatal('No directories configured in section %s',
                          section_name)
            sys.exit(1)
        else:
            dirs = json.loads(dirs)
        pattern = section.get('pattern', None)
        if pattern is not None:
            pattern = re.compile(pattern)
        recursive = section.get('recursive', True)
        snarfer = snarf.LogSnarf(state_object, upl)
        if pattern:
            logging.info(
                'Setting up Snarfer to watch directories %s '
                'pattern: %s recursive: %s', dirs, pattern.pattern, recursive)
        else:
            logging.info(
                'Setting up Snarfer to watch directories %s recursive: %s',
                dirs, recursive)
        for d in dirs:
            snarfer.watch(d, pattern, recursive)
        self.snarfer = snarfer
        self.schema = schema_obj
        self.service = svc
        self.uploader = upl

    def start(self):
        self.snarfer.start()


def main():
    opts = Options()
    try:
        opts.parseOptions()
    except usage.UsageError, e:
        print "%s: %s" % (sys.argv[0], e)
        print "%s: Try --help for usage details." % (sys.argv[0])
        sys.exit(1)
    cfg = config.Config(resource_name=opts['resource_name'],
                        config_file=opts['config_file'])
    cfg.load()
    sections = cfg.get('logsnarf', None)
    if sections is None:
        raise errors.ConfigError('No logsnarf section configured.')
    else:
        try:
            config_apps = json.loads(sections['apps'])
        except json.JSONDecodeError:
            raise errors.ConfigError('No valid apps section in configuration')
    apps = []
    for s in config_apps:
        if s not in cfg.keys():
            raise errors.ConfigError('Application section %s referenced but '
                                     'does not exist. %s', s, sections)
        else:
            apps.append(App(cfg, s))
    for app in apps:
        app.start()

    # noinspection PyUnresolvedReferences
    reactor.run()


if __name__ == '__main__':
    main()
