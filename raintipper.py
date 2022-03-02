from PyQt5 import QtGui
from PyQt5 import QtCore
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import (
	QAction, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGroupBox, QCheckBox, 
	QStackedLayout, QWidget, QGridLayout, QRadioButton, QDoubleSpinBox, QSpinBox,
	QSizePolicy, QLineEdit
)
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from electroncash.i18n import _
from electroncash_gui.qt import MessageBoxMixin
from electroncash_gui.qt.util import (
	PrintError, WindowModalDialog
)

from .util import read_config, write_config, commit_config
from .config import c

from .reddit import Reddit

icon_chaintip = QtGui.QIcon(":icons/chaintip.svg")

class Raintipper(PrintError):
	"""Encapsulates on rain-tipping session instance"""

	def __init__(self, reddit: Reddit):
		self.reddit = reddit

		self.print_error(f"Raintipper instantiated with reddit {self.reddit}")

	def lookupRootObject(self, s: str):
		return "<not implemented>"

	# RedditWorker override
	def do_work(self):
		self.print_error("Raintipper.do_work() called")


class RaintipperInitDialog(WindowModalDialog, PrintError, MessageBoxMixin):
	"""Dialog for initializing a RainTipper instance"""

	def __init__(self, wallet_ui, parent):
		super().__init__(parent=parent, title=_("RainTipper Init Dialog"))
		self.setWindowIcon(icon_chaintip)
		self.wallet_ui = wallet_ui
		self.wallet = self.wallet_ui.wallet # TODO: remove and refactor to increase code clarity?

		# instantiate a Raintipper instance
		self.raintipper = Raintipper(self.wallet_ui.reddit)
		self.wallet_ui.reddit.addWorker(self.raintipper)

		# ensure only a single instance of this dialog to exist per wallet
		assert not hasattr(self.wallet, '_raintipper_init_dialog')
		main_window = self.wallet.weak_window()
		assert main_window
		self.wallet._raintipper_init_dialog = self

		# --- layout ---
		main_layout = QVBoxLayout(self)

		# header
		#main_layout.addWidget(QLabel(_('ChainTipper - settings for wallet "{wallet_name}"').format(wallet_name=self.wallet_ui.wallet_name)), 0, 0, Qt.AlignRight)

		# --- group for root object
		g_root_object = QGroupBox(_("Reddit Root Object"))
		grid = QGridLayout(g_root_object)
		main_layout.addWidget(g_root_object)

		# link or ID entry
		grid.addWidget(QLabel(_('Link or ID')), 0, 1, Qt.AlignRight)
		self.root_object = QLineEdit()
		self.root_object.setText("https://www.reddit.com/r/chaintipper/comments/t3ahbo/raintipper_test/")
		def on_root_object():
			self.print_error(f"looking up root object for '{self.root_object.text()}'")
			self.root_object_found_label.setText(self.raintipper.lookupRootObject(self.root_object.text()))
		self.root_object.editingFinished.connect(on_root_object)
		grid.addWidget(self.root_object, 0, 2)

		# display found object
		grid.addWidget(QLabel(_('Found Reddit Object')), 1, 1, Qt.AlignRight)
		self.root_object_found_label = QLabel(_('<not found>'))
		grid.addWidget(self.root_object_found_label, 1, 2, Qt.AlignLeft)


	'''
		# active when wallet opens
		self.cb_activate_on_open = QCheckBox(_("Activate ChainTipper when wallet '{wallet_name}'' is opened.").format(wallet_name=self.wallet_ui.wallet_name))
		self.cb_activate_on_open.setChecked(read_config(self.wallet, "activate_on_wallet_open"))
		def on_cb_activate_on_open():
			write_config(self.wallet, "activate_on_wallet_open", self.cb_activate_on_open.isChecked())
		self.cb_activate_on_open.stateChanged.connect(on_cb_activate_on_open)
		grid.addWidget(self.cb_activate_on_open)

		# mark read digested
		self.cb_mark_read_digested_tips = QCheckBox(_("Keep my inbox clean by marking messages/comments as read when they are digested"))
		self.cb_mark_read_digested_tips.setChecked(read_config(self.wallet, "mark_read_digested_tips"))
		def on_cb_mark_read_digested_tips():
			write_config(self.wallet, "mark_read_digested_tips", self.cb_mark_read_digested_tips.isChecked())
		self.cb_mark_read_digested_tips.stateChanged.connect(on_cb_mark_read_digested_tips)
		grid.addWidget(self.cb_mark_read_digested_tips)

		# --- group Default Tip Amount ------------------------------------------------------------------------------------------

		main_layout.addStretch(1)

		gbox = QGroupBox(_("Default Tip Amount (used when amount parsing fails)"))
		grid = QGridLayout(gbox)
		main_layout.addWidget(gbox)

		# amount
		grid.addWidget(QLabel(_('Amount')), 0, 1, Qt.AlignRight)
		self.default_amount = QLineEdit()
		self.default_amount.setText(read_config(self.wallet, "default_amount"))
		def on_default_amount():
			try:
				self.default_amount.setText(str(decimal.Decimal(self.default_amount.text())))
			except decimal.InvalidOperation as e:
				self.show_error(_("Cannot parse {string} as decimal number. Please try again.").format(string=self.default_amount.text()))
				self.default_amount.setText(read_config(self.wallet, "default_amount"))
			write_config(self.wallet, "default_amount", self.default_amount.text())
		self.default_amount.editingFinished.connect(on_default_amount)
		grid.addWidget(self.default_amount, 0, 2)

		# currency
		self.currencies = sorted(self.wallet_ui.window.fx.get_currencies(self.wallet_ui.window.fx.get_history_config()))
		grid.addWidget(QLabel(_('Currency')), 1, 1, Qt.AlignRight)
		self.default_amount_currency = QComboBox()
		self.default_amount_currency.addItems(self.currencies)
		self.default_amount_currency.setCurrentIndex(
			self.default_amount_currency.findText(
				read_config(self.wallet, "default_amount_currency")
			)
		)
		def on_default_amount_currency():
			write_config(self.wallet, "default_amount_currency", self.currencies[self.default_amount_currency.currentIndex()])
		self.default_amount_currency.currentIndexChanged.connect(on_default_amount_currency)
		grid.addWidget(self.default_amount_currency, 1, 2)


		# --- group Linked Default Tip Amount ----------------------------------------------------------------------------------

		main_layout.addStretch(1)

		self.gbox_linked_amount = QGroupBox(_("Special Linked Default Tip Amount (used when amount parsing fails and recipient has linked an address)"))
		self.gbox_linked_amount.setCheckable(True)
		self.gbox_linked_amount.setChecked(read_config(self.wallet, "use_linked_amount"))
		grid = QGridLayout(self.gbox_linked_amount)
		main_layout.addWidget(self.gbox_linked_amount)
		def on_gbox_linked_amount():
			write_config(self.wallet, "use_linked_amount", self.gbox_linked_amount.isChecked())
		self.gbox_linked_amount.toggled.connect(on_gbox_linked_amount)

		# amount
		grid.addWidget(QLabel(_('Amount')), 0, 1, Qt.AlignRight)
		self.default_linked_amount = QLineEdit()
		self.default_linked_amount.setText(read_config(self.wallet, "default_linked_amount"))
		def on_default_linked_amount():
			try:
				self.default_linked_amount.setText(str(decimal.Decimal(self.default_linked_amount.text())))
			except decimal.InvalidOperation as e:
				self.show_error(_("Cannot parse {string} as decimal number. Please try again.").format(string=self.default_linked_amount.text()))
				self.default_linked_amount.setText(read_config(self.wallet, "default_linked_amount"))
			write_config(self.wallet, "default_linked_amount", self.default_linked_amount.text())
		self.default_linked_amount.editingFinished.connect(on_default_linked_amount)
		grid.addWidget(self.default_linked_amount, 0, 2)

		# currency
		self.currencies = sorted(self.wallet_ui.window.fx.get_currencies(self.wallet_ui.window.fx.get_history_config()))
		grid.addWidget(QLabel(_('Currency')), 1, 1, Qt.AlignRight)
		self.default_linked_amount_currency = QComboBox()
		self.default_linked_amount_currency.addItems(self.currencies)
		self.default_linked_amount_currency.setCurrentIndex(
			self.default_linked_amount_currency.findText(
				read_config(self.wallet, "default_linked_amount_currency")
			)
		)
		def on_default_linked_amount_currency():
			write_config(self.wallet, "default_linked_amount_currency", self.currencies[self.default_linked_amount_currency.currentIndex()])
		self.default_linked_amount_currency.currentIndexChanged.connect(on_default_linked_amount_currency)
		grid.addWidget(self.default_linked_amount_currency, 1, 2)


		# --- group autopay ---------------------------------------------------------------------------------------------------

		main_layout.addStretch(1)

		self.gbox_autopay = QGroupBox(_("AutoPay - Automatically pay unpaid tips"))
		self.gbox_autopay.setCheckable(True)
		self.gbox_autopay.setChecked(read_config(self.wallet, "autopay"))
		vbox = QVBoxLayout(self.gbox_autopay)
		main_layout.addWidget(self.gbox_autopay)
		def on_gbox_autopay():
			write_config(self.wallet, "autopay", self.gbox_autopay.isChecked())
			#on_cb_autopay_limit()
		self.gbox_autopay.toggled.connect(on_gbox_autopay)

		# disallow autopay when default amount is used
		self.cb_autopay_disallow_default = QCheckBox(_("Disallow AutoPay when Default Tip Amount is used"))
		self.cb_autopay_disallow_default.setChecked(read_config(self.wallet, "autopay_disallow_default"))
		def on_cb_autopay_disallow_default():
			write_config(self.wallet, "autopay_disallow_default", self.cb_autopay_disallow_default.isChecked())
		self.cb_autopay_disallow_default.stateChanged.connect(on_cb_autopay_disallow_default)
		vbox.addWidget(self.cb_autopay_disallow_default)

		# autopay limit checkbox
		self.cb_autopay_limit = QCheckBox(_("Limit AutoPay Amount"))
		self.cb_autopay_limit.setChecked(read_config(self.wallet, "autopay_use_limit"))
		def on_cb_autopay_limit():
			self.autopay_limit_bch_label.setEnabled(self.gbox_autopay.isChecked() and self.cb_autopay_limit.isChecked())
			self.autopay_limit_bch.setEnabled(self.gbox_autopay.isChecked() and self.cb_autopay_limit.isChecked())
			write_config(self.wallet, "autopay_use_limit", self.cb_autopay_limit.isChecked())
		self.cb_autopay_limit.stateChanged.connect(on_cb_autopay_limit)
		vbox.addWidget(self.cb_autopay_limit)

		# autopay limit (amount)
		hbox = QHBoxLayout()
		vbox.addLayout(hbox)
		self.autopay_limit_bch_label = QLabel(_('AutoPay Limit (BCH per Tip)'))
		hbox.addWidget(self.autopay_limit_bch_label, 10, Qt.AlignRight)
		self.autopay_limit_bch = QLineEdit()
		self.autopay_limit_bch.setText(read_config(self.wallet, "autopay_limit_bch"))
		def on_autopay_limit_bch():
			write_config(self.wallet, "autopay_limit_bch", self.autopay_limit_bch.text())
		self.autopay_limit_bch.editingFinished.connect(on_autopay_limit_bch)
		hbox.addWidget(self.autopay_limit_bch, 40)

		# ensure correct enable state
		#on_cb_autopay()


		# close button
		cbut = CloseButton(self)
		main_layout.addLayout(Buttons(cbut))
		cbut.setDefault(False)
		cbut.setAutoDefault(False)
	'''
	
	def closeEvent(self, event):
		super().closeEvent(event)
		self.wallet_ui.reddit.removeWorker(self.raintipper)
		#commit_config(self.wallet)
		if event.isAccepted():
			self.setParent(None)
			del self.wallet._raintipper_init_dialog

	def showEvent(self, event):
		super().showEvent(event)
