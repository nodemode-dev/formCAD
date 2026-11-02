import importlib
import pkgutil

for _info in pkgutil.iter_modules(__path__):
    importlib.import_module(__name__ + "." + _info.name)
