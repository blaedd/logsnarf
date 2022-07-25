#!/usr/bin/env python
# -*- coding: utf-8 -*-
# -*- test-case-name: logsnarf.test.test_state -*-

"""Persistant state

Basically just a wrapper around a dict that saves on mutate. This doesn't
change often, so is fine for our needs at the moment.
"""

import os
import os.path
import collections
import json
import logging


class State(collections.MutableMapping):
    """A persistent dictionary.

    State is initially loaded from a json encoded file. State is saved to
    that file on every mutate.
    """

    def __init__(self, state_path):
        """Create the state object from a file.

        :param state_path: Path the JSON encoded state file.
        :type state_path: string
        """
        super(State, self).__init__()
        self._values = {}
        self.state_path = state_path
        self.log = logging.getLogger(self.__class__.__name__)
        try:
            with open(state_path) as f:
                self._values.update(json.load(f))
        except IOError:
            if os.path.exists(state_path):
                self.log.error('Unable to open state file %s', state_path)
                raise
            self.log.warn('State file %s does not exist.', state_path)
            if not os.access(os.path.dirname(state_path), os.W_OK):
                self.log.error('Unable to write to state file %s', state_path)
                raise
        except ValueError:
            self.log.error('Invalid state file %s ignoring', state_path)

    def __len__(self):
        return self._values.__len__()

    def __setitem__(self, key, value):
        v = self._values.__setitem__(key, value)
        self.save()
        return v

    def __delitem__(self, key):
        v = self._values.__delitem__(key)
        self.save()
        return v

    def __iter__(self):
        return self._values.__iter__()

    def __getitem__(self, key):
        return self._values.__getitem__(key)

    def save(self):
        """Save current state."""
        with open(self.state_path, 'wb') as f:
            json.dump(self._values, f, sort_keys=True)
