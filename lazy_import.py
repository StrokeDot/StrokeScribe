"""A module loaded the first time it is used (exp.130: OpenCV took a noticeable part of
starting the app, and Home does not need it)."""
import importlib


class Lazy:
    def __init__(self, name):
        self.__dict__['_name'] = name
        self.__dict__['_module'] = None

    def _load(self):
        module = self.__dict__['_module']
        if module is None:
            module = importlib.import_module(self.__dict__['_name'])
            self.__dict__['_module'] = module
        return module

    def __getattr__(self, attr):
        return getattr(self._load(), attr)

    def __repr__(self):
        return f'<lazy {self.__dict__["_name"]}>'
