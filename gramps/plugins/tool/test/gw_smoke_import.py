import gramps.plugins.tool.test.gw_stubs as gw_stubs
import importlib

for m in [
    "gwizardcitationshared",
    "gwizardcitationrepairengine",
    "gwizardcitationreport",
    "gw_repoconsolidatedialog",
    "gw_repomergedialog",
    "gw_sourcesfixdialog",
    "gw_unpacksourcesdialog",
    "gw_unpackcitationsdialog",
    "gw_citationsfixdialog",
    "gw_citationattributesdialog",
    "gw_notesfixdialog",
    "gwizardcitationfix",
]:
    importlib.import_module("gramps.plugins.tool." + m)
    print("imported", m)
