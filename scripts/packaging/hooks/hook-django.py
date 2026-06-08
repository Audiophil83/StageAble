"""PyInstaller hook for Django — uses the RemoteAble project package directly."""

# Apps often omit optional templatetags/context_processors subpackages.
warn_on_missing_hiddenimports = False

import glob
import os
from pathlib import Path

from PyInstaller import log as logging
from PyInstaller.utils import hooks
from PyInstaller.utils.hooks import django

logger = logging.getLogger(__name__)

_SKIP_SUBMODULE_PREFIXES = ("django.contrib.postgres",)


def _include_submodule(name: str) -> bool:
    return not any(
        name == prefix or name.startswith(prefix + ".")
        for prefix in _SKIP_SUBMODULE_PREFIXES
    )


datas, binaries, hiddenimports = hooks.collect_all(
    "django",
    filter_submodules=_include_submodule,
    on_error="ignore",
)

root_dir = str(Path(__file__).resolve().parents[3] / "remoteable")
if os.path.isdir(root_dir):
    logger.info("Django root directory %s", root_dir)
    settings_py_imports = django.django_dottedstring_imports(root_dir)
    for submod in settings_py_imports:
        hiddenimports.append(submod)
        hiddenimports += hooks.collect_submodules(submod, on_error="ignore")

    package_name = os.path.basename(root_dir)
    default_settings_module = f"{package_name}.settings"
    settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", default_settings_module)
    hiddenimports += [
        settings_module,
        package_name + ".urls",
        package_name + ".wsgi",
        package_name + ".asgi",
        "http.cookies",
        "html.parser",
    ]

    logger.info("Collecting Django migration scripts.")
    migration_modules = [
        "django.conf.app_template.migrations",
        "django.contrib.admin.migrations",
        "django.contrib.auth.migrations",
        "django.contrib.contenttypes.migrations",
        "django.contrib.flatpages.migrations",
        "django.contrib.redirects.migrations",
        "django.contrib.sessions.migrations",
        "django.contrib.sites.migrations",
    ]
    installed_apps = hooks.get_module_attribute(settings_module, "INSTALLED_APPS")
    migration_modules.extend(set(app + ".migrations" for app in installed_apps))
    for mod in migration_modules:
        mod_name, bundle_name = mod.split(".", 1)
        mod_dir = os.path.dirname(hooks.get_module_file_attribute(mod_name))
        bundle_dir = bundle_name.replace(".", os.sep)
        pattern = os.path.join(mod_dir, bundle_dir, "*.py")
        for f in glob.glob(pattern):
            datas.append((f, os.path.join(mod_name, bundle_dir)))

    datas += hooks.collect_data_files(package_name)
else:
    logger.warning("No django root directory could be found!")
