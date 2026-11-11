"""Test stubs: lets the GWizard modules import without GTK. Set GWIZARD_PLUGIN_DIR to the folder holding the plugin .py files (default: parent of tests/)."""

import sys, types


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _mk(name)


def _mk(name):
    return _Meta(
        name,
        (object,),
        {
            "__init__": lambda self, *a, **k: None,
            "__getattr__": lambda self, n: (
                (_ for _ in ()).throw(AttributeError(n))
                if n.startswith("__")
                else _mk(n)()
            ),
            "__call__": lambda self, *a, **k: _mk("r")(),
        },
    )


def _module(name):
    m = types.ModuleType(name)
    m.__getattr__ = lambda n: _mk(n)
    sys.modules[name] = m
    return m


import gi
import gi.repository as _repo

for _n in ("Gtk", "Gdk", "Pango"):
    _m = _module("gi.repository." + _n)
    setattr(_repo, _n, _m)
for n in (
    "gramps.gui.dialog",
    "gramps.gui.managedwindow",
    "gramps.gui.plug",
    "gramps.gui.utils",
):
    _module(n)

import gramps.plugins.tool as tool_pkg
import os

tool_pkg.__path__.insert(
    0,
    os.environ.get("GWIZARD_PLUGIN_DIR", os.path.join(os.path.dirname(__file__), "..")),
)
