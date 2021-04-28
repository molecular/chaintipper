from electroncash.i18n import _
from electroncash.plugins import BasePlugin, hook
from .wallet_ui import WalletUI
from .util import read_config, write_config

class Plugin(BasePlugin):
	electrumcash_qt_gui = None

	def __init__(self, parent, config, name):
		BasePlugin.__init__(self, parent, config, name)

		self.wallet_uis = {}

	def fullname(self):
		return 'ChainTipper'

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
		#self.wallet_uis[wallet.basename()].close()
		# window = self.wallet_windows[wallet_name]
		# del self.wallet_windows[wallet_name]
		# self.remove_ui_for_wallet(wallet_name, window)
