from dynaconf import Dynaconf
import os

current_directory = os.path.dirname(os.path.realpath(__file__))
settings = Dynaconf(
    root_path=current_directory,
    envvar_prefix=False,  # Load all environment variables
    settings_files=['settings.yaml', '.secrets.yaml'],
    merge_enabled=True
)