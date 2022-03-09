from PyQt5 import QtGui
from PyQt5 import QtCore
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import (
	QAction, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QGroupBox, QCheckBox, 
	QStackedLayout, QWidget, QGridLayout, QRadioButton, QDoubleSpinBox, QSpinBox,
	QSizePolicy, QLineEdit
)
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication

from electroncash.i18n import _
from electroncash_gui.qt import ElectrumWindow
from electroncash_gui.qt.util import webopen, MessageBoxMixin, MyTreeWidget
from electroncash_gui.qt.util import (
	PrintError,
	Buttons, CancelButton, CloseButton, OkButton,
	WindowModalDialog
)

from .util import read_config, write_config, commit_config
from .config import c

from .reddit import Reddit, RedditWorker
from . import praw

icon_chaintip = QtGui.QIcon(":icons/chaintip.svg")

#######################################################################################################
#                                                                                                     #
#    88888888ba             88                    88                                                  #
#    88      "8b            ""              ,d    ""                                                  #
#    88      ,8P                            88                                                        #
#    88aaaaaa8P' ,adPPYYba, 88 8b,dPPYba, MM88MMM 88 8b,dPPYba,  8b,dPPYba,   ,adPPYba, 8b,dPPYba,    #
#    88""""88'   ""     `Y8 88 88P'   `"8a  88    88 88P'    "8a 88P'    "8a a8P_____88 88P'   "Y8    #
#    88    `8b   ,adPPPPP88 88 88       88  88    88 88       d8 88       d8 8PP""""""" 88            #
#    88     `8b  88,    ,88 88 88       88  88,   88 88b,   ,a8" 88b,   ,a8" "8b,   ,aa 88            #
#    88      `8b `"8bbdP"Y8 88 88       88  "Y888 88 88`YbbdP"'  88`YbbdP"'   `"Ybbd8"' 88            #
#                                                    88          88                                   #
#                                                    88          88                                   #
#######################################################################################################

class Raintipper(RedditWorker, QWidget):
	"""Encapsulates on rain-tipping session instance"""
	root_object_located = pyqtSignal(object)

	def __init__(self, wallet_ui):
		RedditWorker.__init__(self)
		QWidget.__init__(self)
		self.wallet_ui = wallet_ui
		self.reddit = self.wallet_ui.reddit
		self.window = self.wallet_ui.window
		self.stage = 'init'

		self.tab = None
		self.previous_tab = None

		self.print_error(f"Raintipper instantiated with reddit {self.reddit}")

		# signal for Raintipper.do_work() to inform about located root object

	def locateRootObject(self, s: str):
		self.stage = 'locate_root_object'
		self.root_object_text = s
		self.desired_interval_secs = 0

	def createTab(self):
		if self.tab:
			self.destroyTab()
		self.tab = self.window.create_list_tab(self)
		self.window.tabs.addTab(self.tab, icon_chaintip, 'Rain_' + self.root_object.id)

	def destroyTab(self, name):
		if self.tab:
			self.window.tabs.removeTab(self.window.tabs.indexOf(self.tab))
		self.tab = None

	def show_tab(self):
		"""switch main window to our tab"""
		if self.tab:
			self.previous_tab_index = self.window.tabs.currentIndex()
			self.window.tabs.setCurrentIndex(self.window.tabs.indexOf(self.tab))

	# def show_previous_tab(self):
	# 	"""switch main window back to tab selected when show_chaintipper_tab() was called"""
	# 	self.print_error("previous tab index:", self.previous_tab_index)
	# 	if self.previous_tab_index != None:
	# 		self.window.tabs.setCurrentIndex(self.previous_tab_index)
	# 		self.previous_tab_index = None

	# RedditWorker override (runs in reddit thread)
	def do_work(self):
		"""called periodically by reddit thread. Multithreading caveats apply, specially when communicating with gui threads"""

		self.print_error("Raintipper.do_work() called, stage: ", self.stage)
		if self.stage == 'locate_root_object':
			self.print_error(f"looking up root object for '{self.root_object_text}'")						
			o = None

			# look for a Comment by url
			try:
				o = self.reddit.reddit.comment(url=self.root_object_text)
			except Exception as e: o = None

			# look for a Submission by url
			if not o: 
				try:
					o = self.reddit.reddit.submission(url=self.root_object_text)
				except Exception as e: o = None

			# signal found object (or "<not found>")
			if o:
				self.print_error("found reddit object", o, "of type", type(o))
				self.root_object = o
				self.root_object_located.emit(o)
				self.stage = 'collect'
			else:
				self.root_object_located.emit("<not found>")


		elif self.stage == 'collect':

			# after initial collect, slow down worker
			self.desired_interval_secs = 15

			# collect
			self.collect()

	def collect(self, o=None):
		self.print_error(f"collecting o={o}")

		if o == None: # start at self.root_object
			o = self.root_object

		# create Raintip based on comment
		elif type(o) == praw.models.Comment:
			raintip = Raintip(o)
			self.print_error("collected", raintip)

		# recurse through children
		comment_forest = None
		if type(o) == praw.models.Submission:
			comment_forest = o.comments
		elif type(o) == praw.models.Comment:
			comment_forest = o.replies

		for comment in comment_forest:
			self.collect(comment)


#####################################################################
#                                                                   #
#    88888888ba             88                    88                #
#    88      "8b            ""              ,d    ""                #
#    88      ,8P                            88                      #
#    88aaaaaa8P' ,adPPYYba, 88 8b,dPPYba, MM88MMM 88 8b,dPPYba,     #
#    88""""88'   ""     `Y8 88 88P'   `"8a  88    88 88P'    "8a    #
#    88    `8b   ,adPPPPP88 88 88       88  88    88 88       d8    #
#    88     `8b  88,    ,88 88 88       88  88,   88 88b,   ,a8"    #
#    88      `8b `"8bbdP"Y8 88 88       88  "Y888 88 88`YbbdP"'     #
#                                                    88             #
#                                                    88             #
#####################################################################

class Raintip(PrintError):
	"""constitutes a Raintip based on a reddit comment"""

	def __init__(self, comment: praw.models.Comment):
		self.comment = comment

	def __str__(self):
		return f"Raintip {self.comment.id}"

	def getID(self):
		return self.comment.id

######################################################################################################
#                                                                                                    #
#    88888888ba             88                    88             88          88                      #
#    88      "8b            ""              ,d    ""             88          ""             ,d       #
#    88      ,8P                            88                   88                         88       #
#    88aaaaaa8P' ,adPPYYba, 88 8b,dPPYba, MM88MMM 88 8b,dPPYba,  88          88 ,adPPYba, MM88MMM    #
#    88""""88'   ""     `Y8 88 88P'   `"8a  88    88 88P'    "8a 88          88 I8[    ""   88       #
#    88    `8b   ,adPPPPP88 88 88       88  88    88 88       d8 88          88  `"Y8ba,    88       #
#    88     `8b  88,    ,88 88 88       88  88,   88 88b,   ,a8" 88          88 aa    ]8I   88,      #
#    88      `8b `"8bbdP"Y8 88 88       88  "Y888 88 88`YbbdP"'  88888888888 88 `"YbbdP"'   "Y888    #
#                                                    88                                              #
#                                                    88                                              #
######################################################################################################

class RaintipList(PrintError):

	def __init__(self, raintipper: Raintipper):
		self.raintips = {} # Raintip instances by their getID()

	def addRaintip(self, raintip: Raintip):
		if raintip.getID() in self.raintips.keys():
			raise Exception("RaintipList.addTip(): duplicate raintip.getID()")
		self.raintips[raintip.getID()] = raintip

	def removeRaintip(self, raintip: Raintip):
		del self.raintips[raintip.getID()]


##########################################################################################################################################################################
#                                                                                                                                                                        #
#    88888888ba             88                    88             88          88                 I8,        8        ,8I 88          88                                   #
#    88      "8b            ""              ,d    ""             88          ""             ,d  `8b       d8b       d8' ""          88                          ,d       #
#    88      ,8P                            88                   88                         88   "8,     ,8"8,     ,8"              88                          88       #
#    88aaaaaa8P' ,adPPYYba, 88 8b,dPPYba, MM88MMM 88 8b,dPPYba,  88          88 ,adPPYba, MM88MMM Y8     8P Y8     8P   88  ,adPPYb,88  ,adPPYb,d8  ,adPPYba, MM88MMM    #
#    88""""88'   ""     `Y8 88 88P'   `"8a  88    88 88P'    "8a 88          88 I8[    ""   88    `8b   d8' `8b   d8'   88 a8"    `Y88 a8"    `Y88 a8P_____88   88       #
#    88    `8b   ,adPPPPP88 88 88       88  88    88 88       d8 88          88  `"Y8ba,    88     `8a a8'   `8a a8'    88 8b       88 8b       88 8PP"""""""   88       #
#    88     `8b  88,    ,88 88 88       88  88,   88 88b,   ,a8" 88          88 aa    ]8I   88,     `8a8'     `8a8'     88 "8a,   ,d88 "8a,   ,d88 "8b,   ,aa   88,      #
#    88      `8b `"8bbdP"Y8 88 88       88  "Y888 88 88`YbbdP"'  88888888888 88 `"YbbdP"'   "Y888    `8'       `8'      88  `"8bbdP"Y8  `"YbbdP"Y8  `"Ybbd8"'   "Y888    #
#                                                    88                                                                                 aa,    ,88                       #
#                                                    88                                                                                  "Y8bbdP"                        #
##########################################################################################################################################################################

class RaintipListWidget(PrintError, MyTreeWidget):

	default_sort = MyTreeWidget.SortSpec(1, Qt.AscendingOrder)

	def get_headers(self):
		headers = [
			_('ID'), 
			_('Author'),
		]
		fx = self.window.fx
		
		return headers

	def __init__(self, wallet_ui, window: ElectrumWindow, raintiplist: RaintipList, reddit: Reddit):
		self.wallet_ui = wallet_ui
		self.window = window
		self.reddit = reddit

		MyTreeWidget.__init__(self, window, self.create_menu, self.get_headers(), 10, [],  # headers, stretch_column, editable_columns
							deferred_updates=True, save_sort_settings=True)

		self.updated_raintips = []
		self.added_raintips = []

		self.setRaintiplist(raintiplist)

		if self.reddit == None:
			raise Exception("no reddit")

		self.print_error("RaintipListWidget.__init__()")
		self.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.setSortingEnabled(True)
		self.setIndentation(0)

	def setRaintiplist(self, raintiplist):
		# if hasattr(self, "raintiplist") and self.raiontiplist:
		# 	self.tiplist.unregistertipListener(self)

		self.tips_by_address = dict()
		self.raintiplist = raintiplist

		# connect to tiplist added and update signals
		# self.tiplist.update_signal.connect(self.digestTipUpdates)
		# self.tiplist.added_signal.connect(self.digestTipAdds)

		# # register as TipListener
		# self.tiplist.registerTipListener(self)


	'''
	def __del__(self):
		if self.rainttiplist:
			# clean up signal connections
			# self.tiplist.update_signal.disconnect(self.digestTipUpdates)
			# self.tiplist.added_signal.disconnect(self.digestTipAdds)
			# deregister as tiplistener
			# self.tiplist.unregisterTipListener(self)


	def calculateFiatAmount(self, tip):
		# calc tip.amount_fiat
		d_t = datetime.utcfromtimestamp(tip.chaintip_message_created_utc)
		fx_rate = self.window.fx.history_rate(d_t)

		tip.fiat_currency = self.window.fx.ccy
		if fx_rate and tip.amount_bch:
			try:
				tip.amount_fiat = fx_rate * tip.amount_bch
			except Exception as e:
				self.print_error("error with fx_rate", fx_rate, "tip amount", tip.amount_bch)
				traceback.print_exc(file=sys.stderr)
		else:
			tip.amount_fiat = None

	# TipListener implementation


	def tipAdded(self, tip):
		"""store added tip to local list for later digestion in gui thread"""
		self.added_tips.append(tip)

	def tipUpdated(self, tip):
		"""store updated tip to local list for later digestion in gui thread"""
		self.updated_tips.append(tip)

	def tipRemoved(self, tip):
		if tip.recipient_address:
			del self.tips_by_address[tip.recipient_address]
		if hasattr(tip, 'tiplist_item'):
			if c["use_categories"]:
				category_item = self.getCategoryItemForTip(tip)
				category_item.removeChild(tip.tiplist_item)
			else:
				self.takeTopLevelItem(self.indexOfTopLevelItem(tip.tiplist_item))
			del tip.tiplist_item
		else:
			self.print_error("no tiplist_item")

	def digestTipAdds(self):
		"""actually digest tip adds collected through tipAdded() (runs in gui thread)"""
		added_tips = self.added_tips
		self.added_tips = []

		#if len(added_tips) > 0: self.print_error(f"digesting {len(added_tips)} tip adds")

		for tip in added_tips:
			if tip.recipient_address:
				self.tips_by_address[tip.recipient_address] = tip 

			TipListItem(tip) 
			self.calculateFiatAmount(tip)

			if c["use_categories"]:
				category_item = self.getCategoryItemForTip(tip)
				category_item.setExpanded(True)
				category_item.addChild(tip.tiplist_item)
			else:
				self.addTopLevelItem(tip.tiplist_item)

	def digestTipUpdates(self):
		"""actually digest tip updates collected through tipUpdated() (runs in gui thread)"""
		updated_tips = self.updated_tips
		self.updated_tips = []

		#if len(updated_tips) > 0: self.print_error(f"digesting {len(updated_tips)} tip updates")

		for tip in updated_tips:
			if hasattr(tip, 'tiplist_item'):
				#self.print_error("digesting tip update for tip", tip)
				self.calculateFiatAmount(tip)
				tip.tiplist_item.refreshData()
			else:
				self.updated_tips.append(tip)
				#self.print_error("trying to update tip without tiplistitem: ", tip, ", re-adding to updated_tips list")

	def do_export_history(self, filename):
		self.print_error(f"do_export_history({filename})")

		def csv_encode(s):
			if s is None or len(str(s)) == 0: return ""
			return '"' + str(s).replace('"', '\'') + '"'

		# prepare export_data list
		# export_data = [tip.to_dict() for tip in self.tiplist.tips.values()]
		export_data = []
		for tip in self.tiplist.tips.values():
			d = tip.to_dict()
			d = {**{
				"wallet": self.wallet.basename(),
				"payments": [{
					"txid": txid,
					"amount_bch": str(tip.payments_by_txhash[txid])
				} for txid in tip.payments_by_txhash.keys()]
			}, **d}
			export_data.append(d)

		# write json
		if filename.endswith(".json"):
			with open(filename, "w+", encoding='utf-8') as f:	
				f.write(json.dumps(export_data, indent=4))
			return True

		# write csv
		elif filename.endswith(".csv"):
			for d in export_data:
				self.print_error("dpam", d["payments"])
				d["payments"] = ",".join([p["txid"] for p in d["payments"]])
				self.print_error("d2", d)
			with open(filename, "w+", encoding='utf-8') as f:	
				f.write(",".join([csv_encode(d) for d in export_data[0].keys()]) + '\n')
				for data in export_data:
					f.write(",".join(csv_encode(d) for d in data.values()) + '\n')
			return True

		# extension detection fail
		self.print_error("failed to detect desired file format from extension. Aborting tip export.")
		return False

	def export_dialog(self, tips: list):
		d = WindowModalDialog(self.parent, _('Export {c} Tips').format(c=len(tips)))
		d.setMinimumSize(400, 200)
		vbox = QVBoxLayout(d)
		defaultname = os.path.expanduser(read_config(self.wallet, 'export_history_filename', f"~/ChainTipper tips - wallet {self.wallet.basename()}.csv"))
		select_msg = _('Select file to export your tips to')

		box, filename_e, csv_button = filename_field(self.config, defaultname, select_msg)

		vbox.addWidget(box)
		vbox.addStretch(1)
		hbox = Buttons(CancelButton(d), OkButton(d, _('Export')))
		vbox.addLayout(hbox)

		#run_hook('export_history_dialog', self, hbox)

		#self.update()
		res = d.exec_()
		d.setParent(None) # for python GC
		if not res:
			return
		filename = filename_e.text()
		write_config(self.wallet, 'export_history_filename', filename)
		if not filename:
			return
		success = False
		try:
			# minimum 10s time for calc. fees, etc
			success = self.do_export_history(filename)
		except Exception as reason:
			traceback.print_exc(file=sys.stderr)
			export_error_label = _("Error exporting tips")
			self.parent.show_critical(export_error_label + "\n" + str(reason), title=_("Unable to export tips"))
		else:
			if success:
				self.parent.show_message(_("{l} Tips successfully exported to {filename}").format(l=len(tips), filename=filename))
			else:
				self.parent.show_message(_("Exporting tips to {filename} failed. More detail might be seen in terminal output.").format(filename=filename))



	#

	def create_menu(self, position):
		"""creates context-menu for single or multiply selected items"""

		def doPay(tips: list):
			"""Start semi-automatic payment of a list of tips using the payto dialog ('send' tab)"""
			self.print_error("paying tips: ", [t.getID() for t in tips])
			w = self.parent # main_window

			valid_tips = [tip for tip in tips if tip.isValid() and not tip.isPaid() and tip.amount_bch and isinstance(tip.amount_bch, Decimal)]

			# calc description
			desc, desc_separator = ("chaintip ", "")
			for tip in valid_tips:
				desc += f"{desc_separator}{tip.amount_bch} BCH to u/{tip.username} ({tip.chaintip_message_id})"
				desc_separator = ", "

			# calc payto
			(payto, payto_separator) = ("", "")
			if len(valid_tips) > 1:
				for tip in valid_tips:
					payto += payto_separator + tip.recipient_address.to_string(Address.FMT_CASHADDR) + ', ' + str(tip.amount_bch)
					payto_separator = "\n"
			else:
				payto = valid_tips[0].recipient_address.to_string(Address.FMT_CASHADDR)
				w.amount_e.setText(str(valid_tips[0].amount_bch))

			self.print_error("  desc:", desc)
			self.print_error("  payto:", payto)
			w.payto_e.setText(payto)
			w.message_e.setText(desc)
			w.show_send_tab()

		def doOpenBrowser(path):
			webopen(c["reddit"]["url_prefix"] + path)

		def doOpenBrowserToMessage(message_or_message_id: Union[praw.models.Message, str]):
			if isinstance(message_or_message_id, praw.models.Message):
				message_id = message_or_message_id.id
			else:
				message_id = message_or_message_id
			webopen(c["reddit"]["url_prefix"] + "/message/messages/" + message_id)

		def doOpenBrowserToTippingComment(tip):
			if not hasattr(tip, "tipping_comment"):
				tip.fetchTippingComment()
			self.print_error("tipping comment permalink: ", tip.tipping_comment.permalink)
			doOpenBrowser(tip.tipping_comment.permalink)

		def doOpenBlockExplorerTX(txid: str):
			URL = web.BE_URL(self.config, 'tx', txid)
			webopen(URL)

		def doOpenBlockExplorerAddress(address: Address):
			URL = web.BE_URL(self.config, 'addr', address)
			webopen(URL)

		def doMarkRead(tips: list, include_associated_items: bool = False, unread: bool = False):
			self.reddit.mark_read_tips(tips, include_associated_items, unread)

		def doRemove(tips: list):
			for tip in tips:
				tip.remove()
				del tip

		def doExport(tips: list):
			self.export_dialog(tips)

		col = self.currentColumn()
		column_title = self.headerItem().text(col)

		# put tips into array (single or multiple if selection)
		count_display_string = ""
		tips = [s.tip for s in self.selectedItems()]
		if len(self.selectedItems()) > 1:
			if len(self.selectedItems()) == len(self.tiplist.tips.items()):
				count_display_string = f" (all {len(tips)})"
			else:
				count_display_string = f" ({len(tips)})"

		unpaid_tips = [tip for tip in tips if tip.isValid() and not tip.isPaid() and tip.amount_bch and isinstance(tip.amount_bch, Decimal)]
		unpaid_count_display_string = f" ({len(unpaid_tips)})" if len(tips)>1 else "" 

		# create the context menu
		menu = QMenu()

		if len(tips) == 1:
			tip = tips[0]

			if tip.chaintip_message_id:
				menu.addAction(_("open browser to chaintip message"), lambda: doOpenBrowser("/message/messages/" + tip.chaintip_message_id))

			# open browser...			
			if tip.tippee_content_link:
				menu.addAction(_("open browser to the content that made you tip"), lambda: doOpenBrowser(tip.tippee_content_link))
			if tip.tipping_comment_id:
				menu.addAction(_("open browser to tipping comment"), lambda: doOpenBrowserToTippingComment(tip))
			if hasattr(tip, "chaintip_confirmation_comment") and tip.chaintip_confirmation_comment:
				menu.addAction(_("open browser to chaintip confirmation comment"), lambda: doOpenBrowser(self.reddit.getCommentLink(tip.chaintip_confirmation_comment)))
			if hasattr(tip, "claim_or_returned_message_id") and tip.claim_or_returned_message_id:
				menu.addAction(_('open browser to "{type}" message').format(type="funded" if hasattr(tip, "chaintip_confirmation_status") and tip.chaintip_confirmation_status == "funded" else tip.acceptance_status), lambda: doOpenBrowserToMessage(tip.claim_or_returned_message_id))
			
			# open blockexplorer...

			# ... to payment tx
			menu.addSeparator()
			payment_count = len(tip.payments_by_txhash)
			if payment_count == 1:
				menu.addAction(_("open blockexplorer to payment tx"), lambda: doOpenBlockExplorerTX(list(tip.payments_by_txhash.keys())[0]))
			elif payment_count > 1:
				for tx_hash, amount in list(tip.payments_by_txhash.items())[:5]:
					menu.addAction(_("open blockexplorer to payment tx {tx_hash_short} ({amount} BCH)").format(tx_hash_short=tx_hash[:4]+"..."+tx_hash[-4:], amount=amount), lambda: doOpenBlockExplorerTX(tx_hash))
				if payment_count > 5:
						menu.addAction(_("{count} more tx not shown").format(count=payment_count-5))
				menu.addSeparator()

			# ... to claimed/returned tx
			if hasattr(tip, "claim_return_txid") and tip.claim_return_txid:
				menu.addAction(_("open blockexplorer to {acceptance_status} tx").format(acceptance_status=tip.acceptance_status), lambda: doOpenBlockExplorerTX(tip.claim_return_txid))

			# ... to recipient address
			if hasattr(tip, "recipient_address") and tip.recipient_address:
				menu.addAction(_(f"open blockexplorer to recipient address"), lambda: doOpenBlockExplorerAddress(tip.recipient_address))

		menu.addAction(_("copy recipient address(es)"), lambda: self.wallet_ui.window.app.clipboard().setText("\n".join([tip.recipient_address.to_cashaddr() for tip in tips])))


		# pay...
		if len(unpaid_tips) > 0:
			menu.addSeparator()
			menu.addAction(_(f"pay{unpaid_count_display_string}..."), lambda: doPay(unpaid_tips))

		# export
		menu.addSeparator()
		menu.addAction(_("export{}...").format(count_display_string), lambda: doExport(tips))
		if len(self.selectedItems()) == 1 and len(self.tiplist.tips.items()) > 1:
			menu.addAction(_("export (all {})...").format(len(self.tiplist.tips.items())), lambda: doExport(self.tiplist.tips.items()))

		# remove
		if len(tips) > 0:
			menu.addSeparator()
			menu.addAction(_("remove{}").format(count_display_string), lambda: doRemove(tips))
		
		menu.exec_(self.viewport().mapToGlobal(position))

	'''


########################################################################################################################################################################################
#                                                                                                                                                                                      #
#    88888888ba             88                    88                                               88             88         88888888ba,   88            88                            #
#    88      "8b            ""              ,d    ""                                               88             ""   ,d    88      `"8b  ""            88                            #
#    88      ,8P                            88                                                     88                  88    88        `8b               88                            #
#    88aaaaaa8P' ,adPPYYba, 88 8b,dPPYba, MM88MMM 88 8b,dPPYba,  8b,dPPYba,   ,adPPYba, 8b,dPPYba, 88 8b,dPPYba,  88 MM88MMM 88         88 88 ,adPPYYba, 88  ,adPPYba,   ,adPPYb,d8    #
#    88""""88'   ""     `Y8 88 88P'   `"8a  88    88 88P'    "8a 88P'    "8a a8P_____88 88P'   "Y8 88 88P'   `"8a 88   88    88         88 88 ""     `Y8 88 a8"     "8a a8"    `Y88    #
#    88    `8b   ,adPPPPP88 88 88       88  88    88 88       d8 88       d8 8PP""""""" 88         88 88       88 88   88    88         8P 88 ,adPPPPP88 88 8b       d8 8b       88    #
#    88     `8b  88,    ,88 88 88       88  88,   88 88b,   ,a8" 88b,   ,a8" "8b,   ,aa 88         88 88       88 88   88,   88      .a8P  88 88,    ,88 88 "8a,   ,a8" "8a,   ,d88    #
#    88      `8b `"8bbdP"Y8 88 88       88  "Y888 88 88`YbbdP"'  88`YbbdP"'   `"Ybbd8"' 88         88 88       88 88   "Y888 88888888Y"'   88 `"8bbdP"Y8 88  `"YbbdP"'   `"YbbdP"Y8    #
#                                                    88          88                                                                                                      aa,    ,88    #
#                                                    88          88                                                                                                       "Y8bbdP"     #
########################################################################################################################################################################################

class RaintipperInitDialog(WindowModalDialog, PrintError, MessageBoxMixin):
	"""Dialog for initializing a RainTipper instance"""

	def redditObjectToString(self, o):
		s = None
		if type(o) == praw.models.Submission:
			s = f'Submission "{o.title}"'
		elif type(o) == praw.models.Comment:
			s = f'Comment "{o.body[:10]}"'
		elif type(o) == str:
			return o
		else:
			return f"Unknown type '{type(o)}', str(o): {str(o)}"

		return s + f" by {o.author}"

	def __init__(self, wallet_ui, parent):
		super().__init__(parent=parent, title=_("RainTipper Init Dialog"))
		self.setWindowIcon(icon_chaintip)
		self.wallet_ui = wallet_ui
		self.wallet = self.wallet_ui.wallet # TODO: remove and refactor to increase code clarity?

		# instantiate a Raintipper instance
		self.raintipper = Raintipper(self.wallet_ui)
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
		grid.addWidget(QLabel(_('Reddit URL to Submission or Comment')), 0, 1, Qt.AlignRight)
		self.root_object = QLineEdit()
		self.root_object.setText("https://www.reddit.com/r/chaintipper/comments/t3ahbo/raintipper_test/")
		def on_root_object_entered(): # used lambda for cleaner code
			self.raintipper.locateRootObject(self.root_object.text())
			self.root_object_found_label.setText(_("<looking up reddit object>"))
			#self.raintipper.destroyTab() # destroy tab
		self.root_object.editingFinished.connect(on_root_object_entered)
		grid.addWidget(self.root_object, 0, 2)

		# display found object
		grid.addWidget(QLabel(_('Found Reddit Object')), 1, 1, Qt.AlignRight)
		self.root_object_found_label = QLabel(_('<not found>'))
		grid.addWidget(self.root_object_found_label, 1, 2, Qt.AlignLeft)
		def on_root_object_located(o):
			self.print_error("on_root_object_located: ", o)
			self.root_object_found_label.setText(self.redditObjectToString(o))
			self.gobut.setEnabled(True)
		self.raintipper.root_object_located.connect(on_root_object_located)


		# close button
		cbut = CancelButton(self)
		cbut.setDefault(False)
		cbut.setAutoDefault(False)
		self.gobut = OkButton(self)
		self.gobut.setDefault(False)
		self.gobut.setAutoDefault(False)
		self.gobut.setDisabled(True)
		def on_go():
			self.raintipper.createTab() # create tab
			self.raintipper.show_tab()
		self.gobut.clicked.connect(on_go)
		main_layout.addLayout(Buttons(cbut, self.gobut))

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
