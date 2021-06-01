import os
import queue
import random
import string
import tempfile
import threading
import time
import traceback
import sys
import re

from enum import IntEnum
from decimal import Decimal
from time import sleep
from datetime import datetime

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from electroncash.i18n import _
from electroncash_gui.qt import ElectrumWindow
from electroncash_gui.qt.util import webopen, MessageBoxMixin, MyTreeWidget
from electroncash.transaction import Transaction
from electroncash.util import PrintError, print_error, age, Weak, InvalidPassword, format_time
from electroncash import keystore, get_config
from electroncash.storage import WalletStorage
from electroncash.keystore import Hardware_KeyStore
from electroncash.wallet import Standard_Wallet, Multisig_Wallet
from electroncash.address import Address
from electroncash.wallet import Abstract_Wallet, WalletStorage
import electroncash.web as web

from .model import Tip, TipList, TipListener
from .config import c
from .util import read_config, write_config

from .reddit import Reddit, RedditTip

from . import praw
from . import prawcore


##############################################################################################################################################################
#                                                                                                                                                            #
#    88888888ba                                 88                                           888888888888 88             88          88                      #
#    88      "8b                                ""             ,d                           ,d    88      ""             88          ""             ,d       #
#    88      ,8P                                               88                           88    88                     88                         88       #
#    88aaaaaa8P' ,adPPYba, 8b,dPPYba, ,adPPYba, 88 ,adPPYba, MM88MMM ,adPPYba, 8b,dPPYba, MM88MMM 88      88 8b,dPPYba,  88          88 ,adPPYba, MM88MMM    #
#    88""""""'  a8P_____88 88P'   "Y8 I8[    "" 88 I8[    ""   88   a8P_____88 88P'   `"8a  88    88      88 88P'    "8a 88          88 I8[    ""   88       #
#    88         8PP""""""" 88          `"Y8ba,  88  `"Y8ba,    88   8PP""""""" 88       88  88    88      88 88       d8 88          88  `"Y8ba,    88       #
#    88         "8b,   ,aa 88         aa    ]8I 88 aa    ]8I   88,  "8b,   ,aa 88       88  88,   88      88 88b,   ,a8" 88          88 aa    ]8I   88,      #
#    88          `"Ybbd8"' 88         `"YbbdP"' 88 `"YbbdP"'   "Y888 `"Ybbd8"' 88       88  "Y888 88      88 88`YbbdP"'  88888888888 88 `"YbbdP"'   "Y888    #
#                                                                                                            88                                              #
#                                                                                                            88                                              #
##############################################################################################################################################################

class StorageVersionMismatchException(Exception):
	pass

class PersistentTipList(TipList):
	KEY = "chaintipper_tiplist"
	STORAGE_VERSION = "9"

	def __init__(self, wallet_ui):
		super(PersistentTipList, self).__init__()
		self.wallet_ui = wallet_ui
		self.dirty = False

	def addTip(self, tip):
		super().addTip(tip)
		self.dirty = True

	def removeTip(self, tip):
		super().removeTip(tip)
		self.dirty = True

	def updateTip(self, tip):
		super().updateTip(tip)
		self.dirty = True

	def to_dict(self):
		d = {}
		for id, tip in self.tips.items():
			d[id] = tip.to_dict()
			d[id]["_class_name"] = type(tip).__name__
		return d

	def write_if_dirty(self, storage: WalletStorage):
		if self.dirty:
			d = {
				"version": PersistentTipList.STORAGE_VERSION,
				"tips": self.to_dict()
			}
			storage.put(PersistentTipList.KEY, d)
			self.dirty = False

	def read(self, storage: WalletStorage):
		data = storage.get(PersistentTipList.KEY)
		if not data or not "version" in data.keys() or data["version"] != PersistentTipList.STORAGE_VERSION:
			raise StorageVersionMismatchException("tiplist not in wallet storage or tiplist storage version too old")
		tips = data["tips"]
		for id, d in tips.items():
			# klass = globals()[d["_class_name"]]
			# tip = klass(self)
			class_name = d["_class_name"]
			if class_name == "RedditTip":
				tip = RedditTip(self, self.wallet_ui.reddit)
			tip.from_dict(d)
			assert tip.getID() == id
			self.addTip(tip)
			self.updateTip(tip)

#################################################
#                                               #
#    88                                         #
#    88   ,d                                    #
#    88   88                                    #
#    88 MM88MMM ,adPPYba, 88,dPYba,,adPYba,     #
#    88   88   a8P_____88 88P'   "88"    "8a    #
#    88   88   8PP""""""" 88      88      88    #
#    88   88,  "8b,   ,aa 88      88      88    #
#    88   "Y888 `"Ybbd8"' 88      88      88    #
#                                               #
#                                               #
#################################################

class TipListItem(QTreeWidgetItem, PrintError):

	def __init__(self, o):
		if isinstance(o, list):
			QTreeWidgetItem.__init__(self, o)
		elif isinstance(o, Tip):
			self.tip = o
			self.tip.tiplist_item = self
			self.__init__(self.getDataArray(self.tip))
		else:
			QTreeWidgetItem.__init__(self)

	def getDataArray(self, tip):
		return [
			tip.getID(),
			format_time(tip.chaintip_message_created_utc), 
			tip.read_status,
			tip.acceptance_status,
			tip.payment_status,
			"{0:.8f}".format(tip.amount_received_bch) if isinstance(tip.amount_received_bch, Decimal) else "",
			tip.chaintip_confirmation_status if hasattr(tip, "chaintip_confirmation_status") else "",
			tip.chaintip_message_author_name,
			tip.chaintip_message_subject,
			tip.subreddit_str if hasattr(tip, "subreddit_str") else "",
			tip.username,
			tip.direction,
			tip.tip_amount_text,
			"{0:.8f}".format(tip.amount_bch) if isinstance(tip.amount_bch, Decimal) else "",
			"{0:.2f}".format(tip.amount_fiat) if hasattr(tip, "amount_fiat") and tip.amount_fiat else "",
			tip.fiat_currency if hasattr(tip, "fiat_currency") else "",
			tip.recipient_address.to_ui_string() if tip.recipient_address else None,
			str(tip.tip_quantity),
			tip.tip_unit,
			tip.tipping_comment_id,
			tip.tippee_content_link,
			tip.tippee_post_id,
			tip.tippee_comment_id,
			tip.tipping_comment.body.partition('\n')[0] if hasattr(tip, "tipping_comment") else ""
		]

	def refreshData(self):
		#self.print_error("refreshData() called from", threading.current_thread())
		data = self.getDataArray(self.tip)
		for idx, value in enumerate(data, start=0):
			self.setData(idx, Qt.DisplayRole, value)
			#self.setForeground(idx, Qt.gray if self.tip.read_status == 'read' else Qt.black)			
			self.setForeground(idx, Qt.gray if self.tip.isFinished() else Qt.black)			




###############################################################################
#                                                                             #
#    I8,        8        ,8I 88          88                                   #
#    `8b       d8b       d8' ""          88                          ,d       #
#     "8,     ,8"8,     ,8"              88                          88       #
#      Y8     8P Y8     8P   88  ,adPPYb,88  ,adPPYb,d8  ,adPPYba, MM88MMM    #
#      `8b   d8' `8b   d8'   88 a8"    `Y88 a8"    `Y88 a8P_____88   88       #
#       `8a a8'   `8a a8'    88 8b       88 8b       88 8PP"""""""   88       #
#        `8a8'     `8a8'     88 "8a,   ,d88 "8a,   ,d88 "8b,   ,aa   88,      #
#         `8'       `8'      88  `"8bbdP"Y8  `"YbbdP"Y8  `"Ybbd8"'   "Y888    #
#                                            aa,    ,88                       #
#                                             "Y8bbdP"                        #
###############################################################################

class TipListWidget(PrintError, MyTreeWidget, TipListener):

	default_sort = MyTreeWidget.SortSpec(1, Qt.AscendingOrder)

	def refresh_headers(self):
		headers = [
			_('getID()'), 
			_('Date'),
			_('Read'),
			_('Acceptance'),
			_('Payment'),
			_('Received (BCH)'),
			_('ChainTip'),
			_('Author'), 
			_('Subject'), 
			_('Subreddit'), 
			_('Recipient'), 
			_('Direction'), 
			_('Tip Amount Text'),
			_('Amount (BCH)'),
			"amount_fiat", 
			"fiat_currency",
			_('Recipient Address'),
			_('Tip Quantity'),
			_('Tip Unit'),
			_('Tip Comment ID'), 
			_('Tippee Content Link'),
			_('Tipee post id'),
			_('Tipee comment id'),
			_('Tip Comment body')
		]
		fx = self.window.fx
		
		# replace 'amount_fiat' header
		headers = [_('Amount ({ccy})').format(ccy=fx.ccy) if h=='amount_fiat' else h for h in headers]
		self.update_headers(headers)

	def __init__(self, wallet_ui, window: ElectrumWindow, wallet: Abstract_Wallet, tiplist: TipList, reddit: Reddit):
		MyTreeWidget.__init__(self, window, self.create_menu, [], 10, [],  # headers, stretch_column, editable_columns
							deferred_updates=True, save_sort_settings=True)

		self.wallet_ui = wallet_ui
		self.window = window
		self.wallet = wallet
		self.reddit = reddit

		self.updated_tips = []

		self.setTiplist(tiplist)

		self.refresh_headers()

		if self.reddit == None:
			raise Exception("no reddit")

		self.print_error("TipListWidget.__init__()")
		self.setSelectionMode(QAbstractItemView.ExtendedSelection)
		self.setSortingEnabled(True)
		self.setIndentation(0)


		if c["use_categories"]:
			self.outgoing_items = QTreeWidgetItem([_("outgoing")])
			self.addTopLevelItem(self.outgoing_items)
			self.incoming_items = QTreeWidgetItem([_("incoming")])
			self.addTopLevelItem(self.incoming_items)
			self.other_items = QTreeWidgetItem([_("other messages")])
			#self.addTopLevelItem(self.other_items)

	def __del__(self):
		if self.tiplist:
			self.tiplist.unregistertipListener(self)

	def setTiplist(self, tiplist):
		if hasattr(self, "tiplist") and self.tiplist:
			self.tiplist.unregistertipListener(self)

		self.tiplist = tiplist

		self.tiplist.update_signal.connect(self.digestTipUpdates)

		self.tiplist.registerTipListener(self)
		self.tips_by_address = dict()

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

	def tipUpdated(self, tip):
		self.updated_tips.append(tip)

	def digestTipUpdates(self):
		updated_tips = self.updated_tips
		self.updated_tips = []
		for tip in updated_tips:
			if hasattr(tip, 'tiplist_item'):
				#self.print_error("digesting tip update for tip", tip)
				self.calculateFiatAmount(tip)
				tip.tiplist_item.refreshData()
			else:
				self.updated_tips.append(tip)
				#self.print_error("trying to update tip without tiplistitem: ", tip, ", re-adding to updated_tips list")

	#

	def create_menu(self, position):
		"""creates context-menu for single or multiply selected items"""

		def doPay(tips: list):
			"""Start semi-automatic payment of a list of tips using the payto dialog ('send' tab)"""
			self.print_error("paying tips: ", [t.getID() for t in tips])
			w = self.parent # main_window

			valid_tips = [tip for tip in tips if tip.recipient_address and tip.amount_bch and isinstance(tip.recipient_address, Address) and isinstance(tip.amount_bch, Decimal)]

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

		def doOpenBrowserToMessage(message: praw.models.Message):
			webopen(c["reddit"]["url_prefix"] + "/message/messages/" + message.id)

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

		col = self.currentColumn()
		column_title = self.headerItem().text(col)

		# put tips into array (single or multiple if selection)
		count_display_string = ""
		tips = [s.tip for s in self.selectedItems()]
		if len(self.selectedItems()) > 1:
			count_display_string = f" ({len(tips)})"

		new_tips = [t for t in tips if t.read_status == 'new']
		new_count_display_string = f" ({len(new_tips)})" if len(new_tips)>1 else "" 

		read_tips = [t for t in tips if t.read_status == 'read']
		read_count_display_string = f" ({len(read_tips)})" if len(read_tips)>1 else "" 

		unpaid_tips = [t for t in tips if (t.payment_status != None and t.payment_status[:4] != "paid") and t.amount_bch]
		unpaid_count_display_string = f" ({len(unpaid_tips)})" if len(unpaid_tips)>1 else "" 

		# create the context menu
		menu = QMenu()

		# mark_read
		if len(new_tips) > 0:
			menu.addAction(_("mark read{}").format(new_count_display_string), lambda: doMarkRead(new_tips, True))
			menu.addSeparator()

		# mark_unread 
		if len(read_tips) > 0:
			menu.addAction(_("mark unread{}").format(read_count_display_string), lambda: doMarkRead(read_tips, include_associated_items=True, unread=True))
			menu.addSeparator()

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
			if hasattr(tip, "claim_or_returned_message") and tip.claim_or_returned_message:
				menu.addAction(_('open browser to "{type}" message').format(type="funded" if hasattr(tip, "chaintip_confirmation_status") and tip.chaintip_confirmation_status == "funded" else tip.acceptance_status), lambda: doOpenBrowserToMessage(tip.claim_or_returned_message))
			
			# open blockexplorer...
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
			if hasattr(tip, "recipient_address") and tip.recipient_address:
				menu.addAction(_(f"open blockexplorer to recipient address"), lambda: doOpenBlockExplorerAddress(tip.recipient_address))

		# pay...
		if len(unpaid_tips) > 0:
			menu.addSeparator()
			menu.addAction(_(f"pay{unpaid_count_display_string}..."), lambda: doPay(unpaid_tips))

		# remove
		if len(tips) > 0:
			menu.addSeparator()
			menu.addAction(_("remove{}").format(count_display_string), lambda: doRemove(tips))

		
		menu.exec_(self.viewport().mapToGlobal(position))

	# category items

	def getCategoryItemForTip(self, tip: Tip):
		"""Choose correct category (top level) item base on tip direction""" 
		i = self.other_items
		if tip.direction == 'incoming':
			i = self.incoming_items
		elif tip.direction == 'outgoing':
			i = self.outgoing_items
		return i

