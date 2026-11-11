# Settings for dmgbuild (used by build_app.py --dmg-only). `defines` comes from the command line of build_app.py.
import os

here = os.path.dirname(os.path.abspath(defines["settings_file"] if "settings_file" in defines else __file__))
app_path = defines["app"]
app_name = os.path.basename(app_path)

volume_name = "Privatier"
format = "UDZO"
filesystem = "HFS+"
files = [app_path, os.path.join(here, "First start.txt")]
symlinks = {"Applications": "/Applications"}
icon = os.path.join(here, "icon.icns")  # icon of the mounted disk
background = os.path.join(here, "dmg_background.tiff")

window_rect = ((200, 120), (660, 400))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
icon_size = 112
text_size = 13
icon_locations = {
    app_name: (165, 185),
    "Applications": (495, 185),
    "First start.txt": (330, 290),
}
