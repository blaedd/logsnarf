===============================
The Logsnarf configuration file
===============================

.. contents::

General
+++++++
Logsnarf looks in XDG_CONFIG_DIRS for configuration files by default,
named {RESOURCE_NAME}.ini with a default resource name of 'logsnarf'. So a
user configuration will, by default be (on linux)
~/.config/logsnarf/logsnarf.ini

The same directories are searched for a logging.ini which should be a
:py:func:`logging.config.fileConfig` configuration. If no file is found,
:py:func:`logging.basicConfig` is called with no arguments.

Within the logsnarf config file there must be a logsnarf section with an apps
entry. This should contain a list of sections where the various apps are
configured.

An app is a combination of directories watched, and bigquery upload
information. If you're configuring multiple apps, you can also use the
[DEFAULT] section to provide defaults for these (e.g. upload credentials)


Example
+++++++

An example configuration file::

        [DEFAULT]
        project_number=<your google project number>
        service_email=<service account email address>
        dataset=logging
        keyfile=key.p12
        default_domain=my.domain
        max_buffer=2000
        batchsize=400

        [logsnarf]
        apps=app1, app2
        threadpool_size=20

        [app1]
        table_name_schema=syslog_{YEAR}{MONTH}{DAY}
        directories=["/var/log/syslog/hosts"]
        recursive=True
        pattern=(syslog|.*\.log$)
        schema=syslog_schema.json

        [app2]
        table_name_fmt=apache_{YEAR}{MONTH}{DAY}
        directories=["/var/log/apache"]
        recursive=False
        pattern=(access|error)\.log$


In this example ``schema_file`` for app2 would be ``app2_schema.json``. The state
files would be ``app1_state.json`` and ``app2_state.json`` (using the defaults and
ConfigParser interpolation.)

Configuration file fields
+++++++++++++++++++++++++
Where ``%(value)s`` is listed in a default, it uses
:py:class:`ConfigParser.SafeConfigParser` interpolation. ``__name__`` in this
case refers to the section name.

logsnarf section
================
:apps: list of sections with app configurations
:threadpool_size: **default value: 30**
                  size to set the twisted threadpool. Logsnarf does most
                  uploads and some other table operations in threads.

App sections
============
Fields in an app section are

BigQuery-Service related
------------------------

:dataset: Dataset to upload to
:keyfile: Path to a file with Service account key.
:project_number: Your BigQuery project number
:schema_file: **default value: %(__name__)s_schema.json**

              Filename for a file with a json representation of the BigQuery
              fields This is loaded from the xdg user config directory.
:service email: Service account email address

Logfile related
---------------

:default_tz: **default value: UTC**
             The default timezone to apply if none is available in the data.
:directories: a JSON list of directories to watch for log files
:pattern: **default value:** :regexp:`.*\\.log`
          regexp pattern that files must match to be watched.
:state_file: **default value: %(app_section)s_state.json)**
             state file to store logfile names, inode and last seek position.
             This will be created if it doesn't exist.

BigQuery uploader related
-------------------------
:batchsize: **default value: 250**
            how many log entries to upload in a single request. max 500
:flush_interval: **default value: 30** 
                 Normally the uploader will wait until batchsize log entries are
                 queued before starting an upload, however it will wait at most
                 flush_interval seconds.
:max_buffer: **default value: 1000**
             how many log entries the uploader should buffer from the log
             watcher before pausing the log watcher. You will mainly hit this
             backprocessing files, while every effort is made to flush this
             buffer on exit,
             
             Lines kept here are at risk of loss, since they are
             marked "read" by the log watcher when pushed to the uploader.
             Too low, and you'll be waiting on BigQuery inserts.
:table_name_fmt: **default value: logs_{YEAR}{MONTH}{DAY}**
                    When creating tables, this is used for naming, if the
                    entries don't contain a 'table' field. The schema can 
                    include {YEAR} {MONTH} and {DATE} substitutions, that
                    are taken from a time field in the data, or now if that 
                    field doesn't exist.

Other
-----
:default_domain: used by additional verifiers, to insert a domain on
                 non-qualified hostnames in 'host', 'src.host', or 'dst.host'
                 fields

