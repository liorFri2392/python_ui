# -*- mode: python ; coding: utf-8 -*-
import os
import sys

import PyInstaller.config
from PyInstaller.utils.hooks import copy_metadata

workdir = os.path.join('dist', sys.platform)
if not os.path.exists(workdir):
    os.makedirs(workdir)
PyInstaller.config.CONF['distpath'] = workdir

block_cipher = None
output_file_name = 'similarweb-extract-custom'

added_files = [('./resources/similarweb-banner.jpg', './resources')] + copy_metadata("pycountry")

a = Analysis(['main.py'],
             pathex=['/Users/gfryns/Documents/github/python-api-extract/python-script-template'],
             binaries=[],
             datas=added_files,
             hiddenimports=['pkg_resources.py2_warn'],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          [],
          name=output_file_name,
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=False,
          icon='resources\\similarweb_icon_k6o_icon.ico')
app = BUNDLE(exe,
             name='macos/' + output_file_name + '.app',
             icon='resources/similarweb.icns',
             bundle_identifier=None,
             info_plist={
                 'NSPrincipalClass': 'NSApplication',
                 'NSAppleScriptEnabled': False,
                 'CFBundleDocumentTypes': []
             })
