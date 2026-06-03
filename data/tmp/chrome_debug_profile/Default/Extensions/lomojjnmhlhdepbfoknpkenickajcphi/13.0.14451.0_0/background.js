var inner_split = "#INNERSPLIT_TILDE#";
var current_tabId;
var current_windowId;

var current_url = "";
var pre_tabId = "";

function connectNMApp() {
    var hostName = "com.winzip.wzcourier.webcourier";
    nm_port = chrome.runtime.connectNative(hostName);
    nm_port.onMessage.addListener(onNMReceiveMessage);
    nm_port.onDisconnect.addListener(onNMDisconnected);
}

function onNMDisconnected() {
    nm_port = null;
}

function sendNativeMessage(message) {
    if (nm_port) {
        nm_port.postMessage(message);
    }
}

function onNMReceiveMessage(message) {
    var functionName = message["function"];
    var params = message["params"];
    if (functionName != null && params != null) {
        var paramArray = JSON.parse(params);
        if("zipsendInsertDeliveryUrl" == functionName && paramArray.length == 3) {
            zipsendInsertDeliveryUrl(paramArray[0], paramArray[1], paramArray[2]);
        } else if ("taggingZipSendTableForGmailUrlDeliver" == functionName && paramArray.length == 1) {
            taggingZipSendTableForGmailUrlDeliver(paramArray[0]);
        } else if ("executeScriptAtHtmlContent" == functionName && paramArray.length == 3) {
            executeScriptAtHtmlContent(paramArray[0], paramArray[1], paramArray[2]);
        }
    }
}

function update_url() {
    if (nm_port) {
        chrome.tabs.query({
            active: true,
            currentWindow: true
        }, function(tabs) {
            if (tabs[0]?.url)
            {
                if(tabs[0].url != current_url || pre_tabId != tabs[0].id) {
                    current_url = tabs[0].url;
                    pre_tabId = tabs[0].id;
                    sendNativeMessage("<1>" + current_url + inner_split + pre_tabId);
                }
            }
        });
    }
}

(function init(){
    connectNMApp();
    update_url();
})();

chrome.windows.onFocusChanged.addListener(() => {
    update_url();
});

chrome.tabs.onActivated.addListener(() => {
    update_url();
});

chrome.tabs.onUpdated.addListener(() => {
    update_url();
});

chrome.runtime.onInstalled.addListener(({ reason, version }) => {
    if((reason == chrome.runtime.OnInstalledReason.INSTALL || reason == chrome.runtime.OnInstalledReason.UPDATE) && !nm_port){
        chrome.tabs.create({'url':'http://www.winzip.com/downec.html','active':true}, null);
    }
    chrome.runtime.onMessage.addListener(
        function(request) {
          if (request != null && request.callbackId != null) {
              pluginSetResultCallback(request.callbackId, request.result);
          }
      });
});

function pluginSetResultCallback(callbackId, result) {
    sendNativeMessage("<2>" + callbackId + "#" + JSON.stringify(result));
}

chrome.runtime.onMessage.addListener(
    function(request) {
      if (request != null && request.callbackId != null) {
          pluginSetResultCallback(request.callbackId, request.result);
      }
  });

function convertEscapeCharToLiteral(str) {
    var dst = str.replace(/\\/g, "\\\\");
    dst = dst.replace(/\'/g, "\\\'");
    dst = dst.replace(/\"/g, "\\\"");
    dst = dst.replace(/\r/g, "\\r");
    dst = dst.replace(/\n/g, "\\n");
    dst = dst.replace(/\t/g, "\\t");
    return dst;
}

function executeScriptAtHtmlContent(scriptCode, nativeCallbackId, tab_id) {
    try {
        chrome.tabs.query({
            active: true
        }, function(tabs) {
            if (tabs[0]?.id == tab_id)
            {
                var script = convertEscapeCharToLiteral(scriptCode);

                chrome.tabs.sendMessage(tabs[0]?.id, {function: "excuteJavaScript", params: [script, nativeCallbackId]}, (request) =>{
                    if (request != null && request.callbackId != null) {
                        pluginSetResultCallback(request.callbackId, request.result);
                     }
                     else
                     {
                        pluginSetResultCallback(nativeCallbackId, null);
                     }
                });
            }
        });
    } catch(e) {
        console.log("executeScriptAtHtmlContent exception: " + e);
        pluginSetResultCallback(nativeCallbackId, null);
    }
}

function zipsendInsertDeliveryUrl(p_url, p_deliveryUrl, tab_id){
    chrome.tabs.query({
        active: true
    }, function(tabs) {
        if (tabs[0]?.id == tab_id)
        {
            chrome.tabs.sendMessage(tabs[0]?.id, {function: "zipsendInsertDeliveryUrl", params: [p_url, p_deliveryUrl]});
        }
    });

}

function taggingZipSendTableForGmailUrlDeliver(tab_id) {
    chrome.tabs.query({
        active: true
    }, function(tabs) {
        if (tabs[0]?.id == tab_id)
        {
            chrome.tabs.sendMessage(tabs[0]?.id, {function: "taggingZipSendTableForGmail", params: []});
        }
    });
}