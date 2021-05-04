manual.md

# ChainTipper User Manual

## A note about Safety and Security

Electron Cash Plugin security model is abysmal: a plugin has access to everything inside EC and also all your system stuff like the filesystem.

This means that you have to trust the author of the plugin. Source code for ChainTipper is included in the distribution ZIP file and will be found together with necessary build tools on github (or similar site)

## General Overview and Mode of Operation

ChainTipper is a Electron Cash Plugin to (semi-)automatically pay chaintip tips you make on Reddit.

To do this, ChainTipper connects to Reddit (you authorized it to do so) and reads new items coming into your inbox (it will see both historical unread items and new ones coming in live).

It then parses any private message authored by `/u/chaintip` to see if it's a message telling you payment details about a tip you made.

ChainTipper will get the linked Tip comment (the one you wrote) and parse a payment amount fromatted `/u/chaintip <amount> <unit>`.

### Installation

ChainTipper is an external Electron-Cash Plugin.

To install it, start Electron Cash, then go to `Tools` -> `Installed Plugins`. Use the `Add Plugin` button and locate ChainTipper-x.y-z.zip from your filesystem.

> Note: When updating, you might have to uninstall the previously installed plugin and then **restart Electron-Cash**.

### Running with debug output

To see debug output (and be able to copy it later) you can start Electron Cash from a terminal ("cmd" on windows, "terminal" or similar on linux) with the `-v` (verbose) flag. Try drag & dropping the executable file to the terminal window, then add a space and the `-v` flag, then hit `enter`. 

For convenience you can add `-w <wallet file name>` to directly open a specific wallet.

### Activating ChainTipper on a wallet

> Note: You are strongly advised to use a separate wallet for ChainTipper. Currently ChainTipper handles only standard wallets without a password. Do not put more money into that wallet than you are prepared to lose.

ChainTipper is accessed through an icon in the bottom Status Bar of a wallet window:

![status bar with ChainTipper icon](status_bar_with_icon.png)

Left-clicking the icon will enable / disable ChainTipper on that wallet.

Right-clicking the icon will open the ChainTipper menu.

Once active, ChainTipper will open a tab in the wallet window.

### Authorizing ChainTipper to access your reddit data.

On first activation (on each wallet), ChainTipper will ask you to authorize it. To do this it will open your systems web browser to a page on reddit allowing you to authorize ChainTip. 

After clicking `Allow` on that page, the plugin should receive an authorization token from your browser (it listens on localhost:18763 and the browser will be redirected there by reddit).

This token will be stored inside your wallet file so subsequent activations of ChainTipper should not require any more authorizations from you.

To remove authorization token from your wallet (disconnect reddit account from wallet), use ChainTipper menu item `Forget Reddit Authorization`

To revoke the authorization go to https://reddit.com/prefs/apps.

### The TipList

When ChainTipper is active a `ChainTipper` tab is shown in the window of the respective wallet:

![ChainTipper tab with TipList](chaintipper_tab_with_tiplist.png)

The List shows one item per private message from `/u/chaintip` that is not marked as `read`. The TipList is not persisted to your hard drive, so next time you activate ChainTipper, all messages that are marked as `read` will be gone. This will likely change in future versions.

### Tip actions

Right-clicking an item in the TipList will bring up a context-menu that allows executing actions on the item. It's also possible to select multiple items (using `shift` and/or `ctrl` modifiers and a left mouse button click)

 * **mark read**: marks the corresponding chaintip messages as `read` on reddit. Note that the item(s) will disappear after you've marked them as read in this way.
 * **pay...**: open Send tab with `Pay to` filled out to reflect the currently selected list of items.
 * **open browser to tipping comment**: opens a webprowser to the permlink of your comment that triggered chaintip

### Specifying an amount in your Tip comment

ChainTipper looks up your comment that triggered chaintip to send you a message and parses that for something matching the following pattern:

```
/u/chaintip <amount> <unit>
```

> Known issue: the leading `/` is currently necessary. Will be fixed soon

What exactly you can use for `<amount>` and `<unit>` can be seen by selecting `Show Amount Monikers` in the ChainTip menu.


#### Parser fail => Default Tip Amount

If the parser fails to find above pattern (for example because you didn't spedify an amount), the `default amount` (configurable in settings, see below) will be used to set the tip amount. 

### AutoTip

TODO

### Settings

TODO

### Handling and Reporting Errors

Especially during the beta, getting error reports to the developers is important.

On fatal Exceptions Electron Cash will show a Error Report Dialog saying `Sorry, something went wrong`. Please **DO NOT** currently use the `Send Bug Report` button, because that will result in an issue being openend in the Electron Cash github. I'm trying to find a way to route the reports to me somehow, but for now, just screenshot or copypaste what is shown when you click `show report contents` and send it to the dev.

Some less fatal errors / problems do not reach this dialog. They can only be seen on the stdout when you start EC from a terminal like described further up in Section "Running with debug output"

![example error report content](example_error_content.png)

## Random Tips & Tricks

 * When you "mark unread" a message in reddit, it will be picked up by ChainTipper
 * There is a setting in reddit user preferences to disable automatically marking messages as read when visiting the inbox.
