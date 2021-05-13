from electroncash.i18n import _
from electroncash.plugins import BasePlugin, hook
from electroncash_gui.qt.util import webopen

from .wallet_ui import WalletUI
from .util import read_config, write_config
from .update_checker import UpdateChecker
from . import fullname

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox
from PyQt5 import QtGui


icon_chaintip = QtGui.QIcon(":icons/chaintip.svg")

class Plugin(BasePlugin):
	electrumcash_qt_gui = None

	def __init__(self, parent, config, name):
		BasePlugin.__init__(self, parent, config, name)

		self.wallet_uis = {}
		self.update_checker_ran = False

	def fullname(self):
		return fullname

	def diagnostic_name(self):
		return "ChainTipper"

	def description(self):
		return _("Chaintip auto-tipping bot")

	def on_close(self):
		"""
		BasePlugin callback called when the wallet is disabled among other things.
		"""
		# for window in list(self.wallet_windows.values()):
		# 	self.close_wallet(window.wallet)
		self.print_error("++++++++++++++++++++++ plugin.on_close() called")
		for wallet_ui in list(self.wallet_uis.values()):
			wallet_ui.close()

	@hook
	def update_contact(self, address, new_entry, old_entry):
		self.print_error("update_contact", address, new_entry, old_entry)

	@hook
	def delete_contacts(self, contact_entries):
		self.print_error("delete_contacts", contact_entries)

	@hook
	def init_qt(self, qt_gui):
		"""
		Hook called when a plugin is loaded (or enabled).
		"""
		self.electrumcash_qt_gui = qt_gui
		# We get this multiple times.  Only handle it once, if unhandled.
		if len(self.wallet_uis):
			return

		# These are per-wallet windows.
		for window in self.electrumcash_qt_gui.windows:
			self.load_wallet(window.wallet, window)

	@hook
	def load_wallet(self, wallet, window):
		"""
		Hook called when a wallet is loaded and a window opened for it.
		Instantiates WalletUI for given wallet in given window and stores it in wallet_uis 
		"""
		self.runUpdateChecker(window)

		wallet_name = window.wallet.basename()

		self.print_error("load_wallet(", wallet_name,")")

		wallet_ui = WalletUI(wallet, window)
		self.wallet_uis[wallet_name] = wallet_ui

		# activate chaintipper if desired by user
		wallet_ui.sbbtn.set_active(read_config(wallet, "activate_on_wallet_open", False))

		#self.wallet_windows[wallet_name] = window

		# self.add_ui_for_wallet(wallet_name, window)
		# self.refresh_ui_for_wallet(wallet_name)

	@hook
	def close_wallet(self, wallet):
		self.print_error("************************ close_wallet (currently does nothing)")
		self.wallet_uis[wallet.basename()].close()
		# window = self.wallet_windows[wallet_name]
		# del self.wallet_windows[wallet_name]
		# self.remove_ui_for_wallet(wallet_name, window)

	# update checker stuff

	def on_auto_update_timeout(self, window):
		self.window_for_updatechecker_messages.show_error("UpdateChecker timeout")

	def getMetainfoText(self, metainfo):
		return "".join([
			"<br><ul>",
			"<li><b>", _("ZIP uri"), "</b>: ", metainfo["uri"], "</li>",
			"<li><b>", _("SHA256(ZIP file)"), "</b>: ", metainfo["sha256"], "</li>",
			"<li><b>", _("Signature CashAccount"), "</b>: ", metainfo["sig_ca"], "</li>",
			"<li><b>", _("Signature Address"), "</b>: ", metainfo["sig_addr"], "</li>",
			"<li><b>", _("Signed Message"), "</b>: ", metainfo["sig_msg"], "</li>",
			"<li><b>", _("Signature (verified)"), "</b>: ", metainfo["sig"], "</li>",
			"</ul>"
		])

	def on_new_version(self, metainfo):
		"""new version available, present info and options to user"""
		choice = self.window_for_updatechecker_messages.msg_box(
			icon = QMessageBox.Question,
			parent = self.window_for_updatechecker_messages,
			title = _("New ChainTipper version {} available").format(metainfo["version"]),
			rich_text = True,
			text = "".join([
				"<h3>", _("New ChainTipper version {} available").format(metainfo["version"]), "</h3>",
				_("The new version will <b>not</b> be automatically installed. You will have to do this manually."), "<br>",
				self.getMetainfoText(metainfo),
				"<b>", _("You can open the download link in your browser."), "</b>"
			]),
			buttons = (_("Open Browser with download link"), _("Not now, close")),
			defaultButton = _("Open Browser"),
			escapeButton = _("Not now, close")
		)
		if choice == 0: # open browser
			webopen(metainfo["uri"])
			self.on_new_version_step2(metainfo)

	def on_new_version_step2(self, metainfo):
		"""new version available, present info and options to user"""
		choice = self.window_for_updatechecker_messages.msg_box(
			icon = QMessageBox.Question,
			parent = self.window_for_updatechecker_messages,
			title = _("New ChainTipper version {} available").format(metainfo["version"]),
			rich_text = True,
			text = "".join([
				"<h3>", _("Verify SHA256sum of {}").format(metainfo["uri"].split('/')[-1]), "</h3>",
				self.getMetainfoText(metainfo),
				"<b>", _("Please find that file and verify the sha256sum matches what is shown here."), "</b><br>",
				_("If it matches you can remove the currently installed version of ChainTipper and install the new one.")
			]),
			buttons = (_("The SHA256 matches. Open 'Installed Plugins'"), _("close")),
			defaultButton = _("The SHA256 matches. Open 'Installed Plugins'"),
			escapeButton = _("close")
		)
		if choice == 0: # open browser
			self.window_for_updatechecker_messages.external_plugins_dialog()

	def on_checked(self, metainfo):
		self.print_error(f"you're running the latest version {metainfo['version']}")

	def on_failed(self, error):
		self.window_for_updatechecker_messages.show_warning(f"UpdateChecker failed with error '{error}'")

	def runUpdateChecker(self, window):
		self.window_for_updatechecker_messages = window
		local_version = self.getVersionFromManifest()
		self.print_error("local_version:", local_version)

		if local_version == 'internal':
			self.print_error("chaintipper runs as 'internal' plugin, aborting update check.")
			return

		if self.update_checker_ran:
			return

		# create and run update checker
		self.update_checker = UpdateChecker(window, local_version)
		self.update_checker_timer = QTimer(window); 
		self.update_checker_timer.timeout.connect(self.on_auto_update_timeout) 
		self.update_checker_timer.setSingleShot(False)

		self.update_checker.got_new_version.connect(self.on_new_version)
		self.update_checker.checked.connect(self.on_checked)
		self.update_checker.failed.connect(self.on_failed)

		# if self.warn_if_no_network(parent):
		# 	return
		# self.update_checker.show()
		# self.update_checker.raise_()
		self.update_checker.do_check()


		self.update_checker_ran = True

	def getVersionFromManifest(self):
		plugins = self.electrumcash_qt_gui.plugins
		self.print_error("------------------------------- plugins:", plugins)
		plugin = plugins.get_external_plugin(self.fullname())

		# for k,v in plugins.external_plugin_metadata.items():
		# 	self.print_error("    k", k, "v", v)

		# if not installed as external plugin (probably dev mode with code linked to electroncash_plugins/chaintipper)
		if plugin is None:
			return 'internal'

		metadata = plugins.external_plugin_metadata[self.fullname()]
		version = metadata["version"]
		return version

		return version
	