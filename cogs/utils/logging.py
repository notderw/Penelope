import logging

class CogLogger(object):
    def __init__(self, name, cls):
        self.cls = cls
        self.log = logging.getLogger(name)

    def __getattr__(self, attr):
        if attr in ['debug', 'info', 'error', 'warning', 'critical']:
            def _handler(*args, **kwargs):
                args = list(args)
                args[0] = f'{self.cls.__class__.__name__} - {args[0]}'
                return self.log.__getattribute__(attr)(*args, **kwargs)
            return _handler

        return self.log.__getattribute__(attr)
