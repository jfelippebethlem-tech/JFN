function zipsendInsertDeliveryUrl(p_url, p_deliveryUrl) {
    var hotmailUrl = 'mail.live.com';
    var outlookUrl = 'outlook.live.com';
    var officeUrl = "outlook.office.com";
    var office365Url = "outlook.office365.com";
    var yahoomailUrl = 'mail.yahoo.com';
    var yahooNewVersionPattern = /yahoo.com(\/dc|\/d)/;
    var gmailUrl = 'mail.google.com';
    var zohomailUrl = 'mail.zoho.com';
    var gmxMailUrl = 'gmx.com/mcstarter/mail.html';
    if (p_url.indexOf(hotmailUrl) != -1) {
        zipsendInsertDeliveryUrlForHotmail(p_deliveryUrl);
    } else if(p_url.indexOf(outlookUrl) != -1) {
        if (p_url.match(/(\/owa)/) != null) {
            zipsendInsertDeliveryUrlForOutlookOldVersion(p_deliveryUrl);
        } else {
            zipsendInsertDeliveryUrlForOutlookNewVersion(p_deliveryUrl);
        }
    } else if(p_url.indexOf(officeUrl) != -1 || p_url.indexOf(office365Url) != -1) {
        zipsendInsertDeliveryUrlForOffice365(p_deliveryUrl);
    } else if(p_url.indexOf(gmailUrl) != -1) {
        zipsendInsertDeliveryUrlForGmail(p_deliveryUrl);
    } else if(p_url.indexOf(yahoomailUrl) != -1) {
        if(p_url.match(yahooNewVersionPattern) != null) {
            zipsendInsertDeliveryUrlForYahoomailNewVersion(p_deliveryUrl);
        } else {
            zipsendInsertDeliveryUrlForYahoomailOldVersion(p_deliveryUrl);
        }
    } else if (p_url.indexOf(zohomailUrl) != -1) {
        zipsendInsertDeliveryUrlForZoho(p_deliveryUrl); 
    } else if (p_url.indexOf(gmxMailUrl) != -1) {
        zipsendInsertDeliveryUrlForGMX(p_deliveryUrl);
    } else {
        return 'Error : URL done not match.';
    }
}

function zipsendInsertDeliveryUrlForGMX(p_deliveryUrl) {
    var textFrame = null;
    var textArea = null;
    var allFrames = document.getElementsByTagName("IFRAME");
    for (var i = 0; i < allFrames.length; i++) {
        try {
            var doc = getContentDocument(allFrames[i]);
            if (doc == null || doc.body.className != "cke_editable cke_editable_themed cke_contents_ltr") {
                continue;
            }
            if (isTextContainer(allFrames[i])) {
                textFrame = allFrames[i];
                break;
            }
        } catch (err) {
            continue;
        }
    }
    if (textFrame != null) {
        var textBody = getContentDocument(textFrame).body;
        var deliveryUrl = getFormatDeliverUrl(p_deliveryUrl, textBody.className);
        textBody.innerHTML = deliveryUrl + textBody.innerHTML;
    } else {
        //This means current editing email using plain text.
        var textAreas = document.getElementsByTagName("TEXTAREA");
        for (var i = 0; i < textAreas.length; i++) {
            if (textAreas[i].className != "qx-placeholder-color") {
                continue;
            }
            if (isTextContainer(textAreas[i])) {
                textArea = textAreas[i];
                break;
            }
        }
        if (textArea != null) {
            textArea.value = getFormatDeliverUrl(p_deliveryUrl, textArea.className) + textArea.value;
        }
    }

}

function isTextContainer(element) {
    var currentNode = element.parentNode;
    var count = 0;
    while (count < 5) {
        switch (count) {
            case 0:
                if (currentNode.id == "mailEditorView") {
                    count++;
                }
                break;
            case 1:
            case 2:
            case 3:
                count++;
                break;
            case 4:
                if (currentNode.style.display != "none") {
                    return true;
                }
                count++;
                break;
            default:
                break;
        }
        currentNode = currentNode.parentNode;
    }
    return false;
}

function zipsendInsertDeliveryUrlForZoho(p_deliveryUrl) {
    var newMail;
    var textFrame;
    var textArea;
    var zmCE = "ze"; // For new version
    var mailList = document.getElementsByClassName(zmCE);
    for (var i = 0; i < mailList.length; i++){
        var temp = mailList[i];
        if (temp.offsetHeight > 0 && temp.offsetWidth > 0) {
           newMail = temp;
           break;
        }
    }
    if (newMail == null) {
        for (var i = 0; i < window.frames.length; i++) {
            var dmt = window.frames[i].document;
            if (dmt == null) {
                continue;
            }
            newMail = dmt.getElementsByClassName(zmCE)[0];
            if (newMail != null) {
                break;
            }
        }
    }

    var tempFrame = newMail.getElementsByClassName("zmComposeFrame")[0];
    var tempTxt = newMail.getElementsByClassName("zmComposeFrame zmComposeTxt")[0];
    if (tempFrame != null && tempFrame.style["display"] != "none") {
        textFrame = tempFrame.getElementsByClassName("ze_area")[0];
    }
    else if (tempTxt != null && tempTxt.style["display"] != "none") {
        textArea = tempTxt.getElementsByClassName("zmTxtArea")[0];
    }
    if (tempFrame == null && textArea == null) {
        var temps = newMail.getElementsByClassName("ze_area");
        for(var i = 0; i < temps.length; i++){
            if(temps[i].nodeName == "IFRAME" && temps[i].style["display"] != "none"){
                textFrame = temps[i];
                break;
            }else if(temps[i].nodeName == "TEXTAREA" && temps[i].style["display"] != "none"){
                textArea = temps[i];
                break;
            }
        }
    }

    if(textFrame != null){
        var textBody = getContentDocument(textFrame).body;
        var deliveryUrl = getFormatDeliverUrl(p_deliveryUrl, "ze_body");
        textBody.innerHTML = deliveryUrl + textBody.innerHTML;
    } else if (textArea != null){
        var deliveryUrl = getFormatDeliverUrl(p_deliveryUrl, "ze_area");
        textArea.value = deliveryUrl + textArea.value;
    }
    setTimeout(function(){document.getElementById("zmAttachCompWhtPopup_closeIcon").click();}, 1); // Click events need to be triggered after the the function returns in IE.
}

function zipsendInsertDeliveryUrlForGmail(p_deliveryUrl) {
    if(hasGmailNewComposeTable()) {
        zipsendInsertDeliveryUrlForGmailNewCompose(p_deliveryUrl);
        return;
    }
    var dmt = document;
    var frame_name = null;
    var textarea_class_name = 'Ak';
    var iframe_class_name = 'Am Al editable';
    var textarea = null;
    var iframe = null;
    var deliverUrl;
    var temps = getElementsByClassName(dmt, textarea_class_name);
    for(i = 0; i < temps.length; i++) {
        if(temps[i].nodeName == 'TEXTAREA') {
            textarea = temps[i];
            break;
        }
    }
    plain_div = textarea.parentNode.parentNode;
    if(plain_div.style.display == 'none') {
        temps = getElementsByClassName(dmt, iframe_class_name);
        for(i = 0; i < temps.length; i++) {
            if(temps[i].nodeName == 'IFRAME') {
                iframe = temps[i];
                break;
            }
        }
        body = iframe.contentDocument.body;
        deliverUrl = getFormatDeliverUrl(p_deliveryUrl, body.className);
        body.innerHTML = deliverUrl + body.innerHTML;
    } else {
        deliverUrl = getFormatDeliverUrl(p_deliveryUrl, textarea.className);
        textarea.value = deliverUrl + textarea.value;
    }
}

function getByClassNames(className) {
    var all = document.all ? document.all : document.getElementsByTagName('*');
    var elements = new Array();
    for(var e = 0; e < all.length; e++) {
        if(all[e].className == className) {
            elements[elements.length] = all[e];
            break;
        }
    }
    return elements;
}

function zipsendInsertDeliveryUrlForHotmail(p_deliveryUrl) {
    var dmt = document;
    var ids = ['appFrame', 'ComposeContent', 'ComposeRteEditor_surface'];
    var deliverUrl;
    var text_classnames = 'RichText PlaceholderText';
    try {
        var appFrame = dmt.getElementById('appFrame');
        var new_document = getContentDocument(appFrame);
        dmt = new_document;
    } catch (e) {
    }
    getElementsByClassName(dmt, text_classnames)[0].innerHTML=" ";
    var mainFrame = get_main_frame(ids, dmt);
    var body = mainFrame.contentDocument.body;
    deliverUrl = getFormatDeliverUrl(p_deliveryUrl, body.className);
    body.innerHTML = deliverUrl + body.innerHTML;
}

function getOutlookEditClassName()
{
    return 'customScrollBar';
}

function getOutlookEditElement()
{
    var plantext = document.getElementsByTagName("textarea");
    if (plantext.length == 1){
        return plantext[0];
    }
    var richtext = document.querySelectorAll('[aria-label="Message body"]');
    if (richtext.length == 1) {
        return richtext[0];
    }
    // "Message body" will be translated in other languages
    var richtext2 = document.querySelectorAll('[role="textbox"],[aria-multiline="true"]');
    if (richtext2.length == 1) {
        return richtext2[0];
    }
    else if (richtext2.length > 1) {
        var index = 0;
        var maxArea = richtext2[0].clientHeight * richtext2[0].clientWidth;
        for (var i = 1; i < richtext2.length; ++i) {
            var area = richtext2[i].clientHeight * richtext2[i].clientWidth;
            if (maxArea < area) {
                maxArea = area;
                index = i;
            }
        }
        return richtext2[index];
    }
    return null;
}

function insertDeliveryUrlForOutlook(p_deliveryUrl)
{
    var body = getOutlookEditElement();
    if (body != null) {
        if (body.tagName == "TEXTAREA") {
            // plan text
            var deliverUrl = getFormatDeliverUrl(p_deliveryUrl, getOutlookEditClassName() + "_plain");
            body.value = deliverUrl + body.value;
            var evt = document.createEvent("Events");
            evt.initEvent("change", true, true);
            body.dispatchEvent(evt);
        } else {
            // html text
            body.focus();
            var deliverUrl = getFormatDeliverUrl(p_deliveryUrl, getOutlookEditClassName());
            body.innerHTML = deliverUrl + body.innerHTML;
        }
    }
}

function zipsendInsertDeliveryUrlForOutlookNewVersion(p_deliveryUrl) {
    insertDeliveryUrlForOutlook(p_deliveryUrl);
    
    var dmt = document;
    var popup = "ms-Dialog-main";
    var panel = getElementsByClassName(dmt, popup)[0];
    if (panel != null){
        panel.style.display = 'none';
        var mainPanel = getElementsByClassName(dmt, "ms-Overlay")[0];
        mainPanel.click();
    }
}

function getOutlookEditClassNameOldVersion()
{
    return 'allowTextSelection ConsumerCED';
}

function getOutlookEditBetaClassNameOldVersion()
{
    return ['_1BD0CHIzklOGMHL1FCsIiW', '_358Bfg3gmi3SvI7tMqlY2C'];
}

function getOutlookEditElementOldVersion()
{
    return document.getElementsByClassName(getOutlookEditClassNameOldVersion())[0]; 
}

function getOutlookBetaEditElementOldVersion()
{
    var ids = getOutlookEditBetaClassNameOldVersion();
    for (i = 0; i < ids.length; i++){
        var betaelement = document.getElementsByClassName(ids[i]);
        if (betaelement.length != 0){
            return betaelement[0];
        }
    }
    return null;
}

function getOutlookPlainTextClassNameOldVersion()
{
    return 'customScrollBar';
}

function getOutlookBetaPlainTextClassNameOldVersion()
{
    return ['_2-s9dD74wgWbEQnHUm6Mog', '_2MR8Ts7Cd6D8UlyJKZuDrM'];
}

function getOutlookPlainTextElementOldVersion()
{
    var temps = document.getElementsByClassName(getOutlookPlainTextClassNameOldVersion());
    for(i=0;i<temps.length;i++){
        if(temps[i].nodeName == 'TEXTAREA'){
            return temps[i];
        }
    }
    return null;
}

function getOutlookBetaPlainTextElementOldVersion()
{
    var ids = getOutlookBetaPlainTextClassNameOldVersion();
    var temps;
    for (i = 0; i < ids.length; i++) {
        temps = document.getElementsByClassName(ids[i]);
        if (temps.length != 0){
            break;
        }
    }
    for (i = 0; i < temps.length; i++) {
        if (temps[i].nodeName == 'TEXTAREA') {
            return temps[i];
        }
    }
    return null;
}

function insertDeliveryUrlForOutlookOldVersion(p_deliveryUrl)
{
    var body = getOutlookEditElementOldVersion();
    var body_beta = getOutlookBetaEditElementOldVersion();

    if (body != null) {
        if (body.parentNode.style.display == 'none') {
            // plain text
            if (getOutlookPlainTextElementOldVersion() != null) {
                body = getOutlookPlainTextElementOldVersion();
            }
            var deliverUrl = getFormatDeliverUrl(p_deliveryUrl, getOutlookPlainTextClassNameOldVersion() + "_plain");
            body.value = deliverUrl + body.value;
        }
        else {
            var deliverUrl = getFormatDeliverUrl(p_deliveryUrl, getOutlookEditClassNameOldVersion());
            body.innerHTML = deliverUrl + body.innerHTML;
        }
    }

    if (body_beta != null) {
            var deliverUrl = getFormatDeliverUrl(p_deliveryUrl, getOutlookEditBetaClassNameOldVersion()[0]);
            body_beta.innerHTML = deliverUrl + body_beta.innerHTML;
    }
    else {
        body_beta = getOutlookBetaPlainTextElementOldVersion();
        // plain text
        if (body_beta != null) {
            var deliverUrl = getFormatDeliverUrl(p_deliveryUrl, getOutlookBetaPlainTextClassNameOldVersion()[0]);
            body_beta.value = deliverUrl + body_beta.value;
        }
    }

    // Hide placeholder
    var placeholders = document.getElementsByClassName('ms-font-color-neutralTertiary');
    for (var i = 0; i < placeholders.length; i++)
    {
        if (placeholders[i].tagName == 'DIV')
        {
            placeholders[i].style.display = 'none';
        }
    }
}

function tryInsertDeliveryUrlForOutlookInPopupOldVersion(p_deliveryUrl, count)
{
    if (count > 10)
    {
        // stop if it is more than 3s
        return;
    }

    var plainParentNode;
    var richParentNode;
    var plainBetaParentNode;
    var richBetaParentNode;

    var plainElement = getOutlookPlainTextElementOldVersion();
    if (plainElement != null)
    {
        plainParentNode = plainElement.parentElement;
    }
    var richElement = getOutlookEditElementOldVersion();
    if (richElement != null)
    {
        richParentNode = richElement.parentElement;
    }

    var plainBetaElement = getOutlookBetaPlainTextElementOldVersion();
    if (plainBetaElement != null) {
        plainBetaParentNode = plainBetaElement.parentElement;
    }
    var richBetaElement = getOutlookBetaEditElementOldVersion();
    if (richBetaElement != null) {
        richBetaParentNode = richBetaElement.parentElement;
    }

    // wait for the rich or plain element load complete.
    if (plainParentNode != null && plainParentNode.style.display != 'none' || richParentNode != null && richParentNode.style.display != 'none')
    {
        insertDeliveryUrlForOutlookOldVersion(p_deliveryUrl);
    }
    else if (plainBetaParentNode != null && plainBetaParentNode.style.display != 'none' || richBetaParentNode != null && richBetaParentNode.style.display != 'none')
    {
        insertDeliveryUrlForOutlookOldVersion(p_deliveryUrl);
    }
    else
    {
        setTimeout(tryInsertDeliveryUrlForOutlookInPopupOldVersion, 300, p_deliveryUrl, count + 1);
    }
}

function zipsendInsertDeliveryUrlForOutlookOldVersion(p_deliveryUrl) {
    var dmt = document;
    var popup = "popupPanel panelPopupShadow";
    var popup_beta = "ms-Dialog-main";
    var panel = getElementsByClassName(dmt, popup)[0];
    var panel_beta = dmt.getElementsByClassName(popup_beta)[0];

    if (panel != null || panel_beta != null){
        // no-popup new mail window
        insertDeliveryUrlForOutlookOldVersion(p_deliveryUrl); // try to set result in no-popup new mail window
        if (panel != null) panel.style.display = 'none';
        else if (panel_beta != null) panel_beta.style.display = 'none';

        var mainPanel = getElementsByClassName(dmt, "modalPanelBackground")[0];
        var mainPanelBeta = dmt.getElementsByClassName("ms-Overlay")[0];
        if (panel != null) mainPanel.click();
        else if (panel_beta != null) mainPanelBeta.click();
    }
    else{
        var buttonClass = '_fc_4 o365buttonLabel _av_Z';
        var buttons = dmt.getElementsByClassName(buttonClass);
        for (var i = 0; i < buttons.length; i++){
            if (buttons[i].parentElement.className.match("ms-bg-color-themePrimary") == null){
                buttons[i].click(); // click on the Cancell button
                break;
            }
        }
        tryInsertDeliveryUrlForOutlookInPopupOldVersion(p_deliveryUrl, 0);
    }
}

// =======================Insert String To Office365=======================
function zipsendInsertDeliveryUrlForOffice365(p_deliveryUrl){
    var dmt = document;
    var textFormat = 'customScrollBar';

    var plantext = document.getElementsByTagName("textarea");
    if (plantext.length == 1) {
        // plain text
        var textarea = plantext[0];
        var deliverUrl = getFormatDeliverUrl(p_deliveryUrl, textFormat + "_plain");
        textarea.value = deliverUrl + textarea.value;
    }
    else {
        var bodyArray = dmt.querySelectorAll('[role="textbox"],[aria-multiline="true"]');
        var body = null;
        if (bodyArray != null) {
            if (bodyArray.length == 1) {
                body = bodyArray[0];
            }
            else {
                var index = 0;
                var maxArea = bodyArray[0].clientHeight * bodyArray[0].clientWidth;
            for(var i = 1; i < bodyArray.length; ++i) {
                    var area = bodyArray[i].clientHeight * bodyArray[i].clientWidth;
                    if (maxArea < area) {
                        maxArea = area;
                        index = i;
                    }
                }
                body = bodyArray[index];
            }
        }

        if (body != null) {
            // rich text
            var deliverUrl = getFormatDeliverUrl(p_deliveryUrl, textFormat);
            body.innerHTML = deliverUrl + body.innerHTML;
        }
        else {
            // plain text
            body = document.querySelector('[placeholder="Add a message"]');
            var deliverUrl = getFormatDeliverUrl(p_deliveryUrl, textFormat + "_plain");
            body.value = deliverUrl + body.value;
        }
    }

    var popup = 'popupPanel panelPopupShadow';
    var panel = getElementsByClassName(dmt, popup)[0];
    if (panel != null)
    {
        panel.style.display = 'none';
    }
    var mainPanel = getElementsByClassName(dmt, 'modalPanelBackground')[0];
    if (mainPanel != null)
    {
        mainPanel.click();
    }
}

function getElementsByClassName(p_document, p_className) {
    return p_document.getElementsByClassName(p_className);
}

function isRichTextInYahooForNewVersion()
{
    var buttons = document.getElementsByTagName('button');
    for (var i = 0; i < buttons.length; i++){
        if (buttons[i].title.search('Switch to rich text mode') != -1){
            // plain-text
            return false;
        }
        if (buttons[i].dataset.testId != null && buttons[i].dataset.testId.search('richtext-on') != -1) {
            return false;
        }
    }
    return true;
}

function clearPlaceholderForYahooNewVersion(targetElement)
{
    try
    {
        var placeholderParent = get_parent_element(targetElement, 3);
        var chileren = placeholderParent.children;
        for (var i = 0; i < chileren.length; i++)
        {
            if (chileren[i].attributes["data-test-id"].value == 'rte_placeholder')
            {
                chileren[i].innerText = "";
            }
        }
    }
    catch (e) { }
}

function saveinnerText(targetElement)
{
    var keyboardEvent = document.createEvent("KeyboardEvent");
    var initMethod = typeof keyboardEvent.initKeyboardEvent !== 'undefined' ? "initKeyboardEvent" : "initKeyEvent";
    keyboardEvent[initMethod](
                        "keypress", // event type : keydown, keyup, keypress
                        true, // bubbles
                        true, // cancelable
                        window, // viewArg: should be window
                        false, // ctrlKeyArg
                        false, // altKeyArg
                        false, // shiftKeyArg
                        false, // metaKeyArg
                        32, // keyCodeArg : unsigned long the virtual key code, else 0
                        0 // charCodeArgs : unsigned long the Unicode character associated with the depressed key, else 0
    );
    targetElement.dispatchEvent(keyboardEvent);
}

function zipsendInsertDeliveryUrlForYahoomailNewVersion(p_deliveryUrl) {
    var dmt = document;
    var frame_id = "rte";
    var targetElement = dmt.getElementsByClassName(frame_id)[0];
    var targetIframe = null;
    var new_version_type = "New YahooMail";
    var isRich = true;
    
    isRich = isRichTextInYahooForNewVersion();
    //clearPlaceholderForYahooNewVersion(targetElement);
    
    if (!isRich) {new_version_type = "YahooMailPlainText";}
    deliverUrl = getFormatDeliverUrl(p_deliveryUrl, new_version_type);
    if (isRich){
        targetElement.childNodes[0].innerHTML = deliverUrl + targetElement.childNodes[0].innerHTML;
    }
    else{
        targetElement.innerHTML = deliverUrl + targetElement.innerHTML;
    }
    saveinnerText(targetElement);
}

function isRichTextInYahoo() {
    var richElement = document.getElementById('switchtext-rich');
    if (richElement.className.indexOf('hidden') >= 0) {
        //plain-text
        return false;
    }
    return true;
}

function isRichTextInSNet() {
    var e = document.getElementById('_test_rich_plain');
    richTexts = ['Switch to Plain Text', 'Plain Text', '切换至纯文本'];
    var text = e.textContent;
    for(var i = 0; i < richTexts.length; ++i) {
        if(text.indexOf(richTexts[i]) >= 0) return true;
    }
    return false;
}

function zipsendInsertDeliveryUrlForYahoomailOldVersion(p_deliveryUrl) {
    var dmt = document;
    var tab_content = "tab-content";
    var targetElement;
    var tabContentList = dmt.getElementsByClassName(tab_content);
    for (var i = 0; i < tabContentList.length; i++) {
        var tabContent = tabContentList[i];
        if (tabContent.className == tab_content && tabContent.style.visibility == "visible") {
            targetElement = tabContent.getElementsByClassName('cm-rtetext')[0];
            break;
        }
    }
    var targetIframe = null;
    var new_version_type = 'New YahooMail';
    var isRich = true;
    isRich = isRichTextInYahoo();
    if(!isRich) {
        new_version_type = 'YahooMailPlainText';
    }
    deliverUrl = getFormatDeliverUrl(p_deliveryUrl, new_version_type);
    targetElement.innerHTML = deliverUrl + targetElement.innerHTML;
}

function get_main_frame(p_frameIds, dmt) {
    var mainFrame;
    for(j = p_frameIds.length - 1; j >= 0; j--) {
        mainFrame = dmt.getElementById(p_frameIds[j]);
        if(mainFrame != null) break;
    }
    if(j < 0) {
        j = 0;
    } else {
        j++;
    }
    for(j; j < p_frameIds.length; j++) {
        if(mainFrame == null) {
            mainFrame = dmt.getElementById(p_frameIds[j]);
        } else {
            tempFrame = getContentDocument(mainFrame).getElementById(p_frameIds[j]);
            if(tempFrame != null) {
                mainFrame = tempFrame;
            }
        }
    }
    return mainFrame;
}

function getContentDocument(iframeObject) {
    var doc;
    if(iframeObject.contentDocument) {
        doc = iframeObject.contentDocument;
    } else if(iframeObject.contentWindow) {
        doc = iframeObject.contentWindow.document;
    }
    return doc;
}

// ==========================Split DeliverURL==========================
var MESSAGE_MARK = {
    POPUP_BEGIN: "#POPUP_MESSAGE_BEGIN#",
    POPUP_END:   "#POPUP_MESSAGE_END#"
};

function getUrlMessageRegExp() {
    var reg = new RegExp("[|]" + MESSAGE_MARK.POPUP_BEGIN + ".*" + MESSAGE_MARK.POPUP_END);
    return reg;
}

function extractContentBetweenMarks(markedStr, beginMark, endMark) {
    var beginIndex = markedStr.indexOf(beginMark) + beginMark.length;
    var content = markedStr.slice(beginIndex, markedStr.lastIndexOf(endMark));
    return content;
}

function spliteDeliverUrlFromMixedUrl(mixedUrl) {
    var reg = getUrlMessageRegExp();
    var deliverUrl = mixedUrl;
    if (mixedUrl.search(reg) != -1) {
        deliverUrl = mixedUrl.replace(reg, "");
    }
    return deliverUrl;
}

function splitMessageFromMixedUrl(mixedUrl) {
    var reg = getUrlMessageRegExp();
    var message = mixedUrl.match(reg);
    if (message && message.length == 1) {
        message = extractContentBetweenMarks(message[0], MESSAGE_MARK.POPUP_BEGIN, MESSAGE_MARK.POPUP_END);
    }
    this.insertLinkFailed = message;
    return this;
}

// =======================Get getCloudServiceMsg For Html=======================
function getCloudServiceMsgForHtml(p_deliverUrl, template_message, template_download) {
    var file_information = "";
    var result = "<table cellpadding=\"10\" cellspacing=\"0\" style=\"border:3px solid #3366CC;\">";
    result += "<tr><td>";
    var cloud_msg = "<span style=\"font-family:Verdana, Geneva, sans-serif; font-size:10pt; color:#333333\">";
    cloud_msg += template_message;
    result += cloud_msg;
    result += "<br><span style='font-size:5px'><br></span><span style='font-size:10pt'>";
    file_information += " <a href=\"" + p_deliverUrl[0] + "\" style=\"color:#3366CC\">";
    file_information += p_deliverUrl[0] + "</a><br></span><span style='font-size:5px'><br></span>";
    result += file_information;
    result = result.replace("*", template_download[0]);
    for (i = 1; i < p_deliverUrl.length; i++) {
        file_information = "";
        if (template_download[i] != template_download[i - 1]) {
            result += cloud_msg;
            result = result.replace("*", template_download[i]);
            result += "<br><span style='font-size:5px'><br></span>"
        }
        result += "<span style='font-size:10pt'>";
        file_information += " <a href=\"" + p_deliverUrl[i] + "\" style=\"color:#3366CC\">";
        file_information += p_deliverUrl[i] + "</a><br></span><span style='font-size:5px'><br></span>";
        result += file_information;
    }
    result += "</td></tr></table><br>";
    return result;
}

// =======================Get getCloudServiceMsg For Text=======================
function getCloudServiceMsgForText(p_deliverUrl, template_message, template_download) {
    var result = template_message + "\r\n";
    result = result.replace("*", template_download[0]);
    result += encodeURI(p_deliverUrl[0]) + "\r\n";
    var url_length = 1;
    for (url_length; url_length < p_deliverUrl.length; url_length++) {
        if (template_download[url_length] != template_download[url_length - 1]) {
            result += template_message + "\r\n";
            result = result.replace("*", template_download[url_length]);
        }
        var encodedDeliverUrl = encodeURI(p_deliverUrl[url_length]);
        result += encodeURI(p_deliverUrl[url_length]) + "\r\n";
    }
    result += "-------------------------------------------------------------------" + "\r\n\r\n";
    return result;
}

//======================Get Result For Html===================================
function getResultForHtml(template_message_html, template_download, p_deliverUrl, file_name) {
    var result = "<table cellpadding=\"10\" cellspacing=\"0\" style=\"border:3px solid #3366CC;\">";
    result += "<tr><td><span style=\"font-family:Verdana, Geneva, sans-serif; font-size:10pt; color:#333333\">";
    result += template_message_html + "<br><span style=\"font-size:5px\"><br></span><span style=\"font-size:14pt\">";
    result += template_download + " <a href=\"" + p_deliverUrl + "\" style=\"color:#3366CC\">";
    result += file_name + "</a><br></span><span style=\"font-size:5px\"><br></span>";
    return result;

}

//======================Get Result For Text===================================
function getResultForText(template_message_plain, template_download_long, file_name, p_deliverUrl, template_expires, expire_date) {
    var result = '';
    var URL_information = "";
    var url_length = 0;
    for (url_length; url_length < p_deliverUrl.length; url_length++) {
        var encodedDeliverUrl = encodeURI(p_deliverUrl[url_length]);
        URL_information += encodedDeliverUrl;
    }

    if (expire_date === ' ') {
        result = template_message_plain + "<br><br>" + template_download_long + " \'";
        result += file_name + "\':<br><br>" + URL_information + "<br><br>";
    } else {
        result = template_message_plain + "<br><br>" + template_download_long + " \'";
        result += file_name + "\':<br><br>" + URL_information + "<br><br>";
        result += template_expires + " " + expire_date + ".<br><br>";
    }
    return result;
}

//======================Get Result Add Hint For Html===================================
function getResultAddHintForHtml(result, template_hint){
    var wz_winzip = '<a href=http://www.winzip.com style=color:#666666>WinZip</a>';
    var wz_zipshare = '<a href=http://www.ZipShare.com style=color:#666666>ZipShare</a>';
    template_hint = template_hint.replace("${FILEEXPIRE}", '<br>');
    template_hint = template_hint.replace("${WINZIP}", wz_winzip);
    template_hint = template_hint.replace("${ZIPSHARE}", wz_zipshare);
    result += template_hint;
    result += "</td></tr></table><br>";
    return result;
}

//======================Get Result Add Hint For Text===================================
function getResultAddHintForText(result, template_hint){
    template_hint = template_hint.replace("${FILEEXPIRE}", '<br>');
    template_hint = template_hint.replace("${WINZIP}", "WinZip (http://www.winzip.com)");
    template_hint = template_hint.replace("${ZIPSHARE}", "ZipShare (http://www.ZipShare.com)");
    result += template_hint + "<br><br>";
    result += "-----------------------" + "<br><br>";
    return result;
}

// =======================Get Format Of DeliverURL=======================
function getFormatDeliverUrl(p_deliverUrl, text) {
    if (p_deliverUrl.indexOf("||") !== -1) {
        var argv_cloud = p_deliverUrl.split("|||");
        var p_deliverUrl_cloud = argv_cloud[0];
        var argv_url = p_deliverUrl_cloud.split("||");
        var p_url = [];
        var url_length = 0;
        var new_url_length = 0;
        for(url_length=1, new_url_length=0; url_length<argv_url.length; url_length++)
        {
            p_url[new_url_length] = argv_url[url_length];
            new_url_length++;
        }
        var c_template_message = argv_cloud[1];
        var c_template_download = argv_cloud[2];
        var cloud_names = c_template_download.split("||");
        switch (text.replace(/[\s]*/g, "")) {
            // Hotmail RTF Format :
            // Gmail RICH Format :
            // Gmail RICH Format new :
            // YahooMail Format:
            case "RichText":
            case "t_mbgct_atcRichText":
            case "HTML":
            case "editableLW-yrriRe":
            case "editableLW-avf":
            case "NewYahooMail":
            case "ze_body":
            case "cke_editablecke_editable_themedcke_contents_ltr":
            case "customScrollBar":
            case "allowTextSelectionConsumerCED":
            case "_1BD0CHIzklOGMHL1FCsIiW":
            case "allowTextSelectioncustomScrollBarowa-font-compose":
                p_deliverUrl_cloud = getCloudServiceMsgForHtml(p_url, c_template_message, cloud_names).replace(/\r\n/g, "<br>");
                break;
            // Hotmail HTML Format :
            case "t_mbgct_atcHTML":
                p_deliverUrl_cloud = getCloudServiceMsgForHtml(p_url, c_template_message, cloud_names).replace(/\r\n/g, "<br>");
                p_deliverUrl_cloud = htmlToEscape(p_deliverUrl_cloud);
                break;
            // Hotmail TEXT Format :
            // Gmail TEXT Format :
            case "PlainText":
            case "t_mbgct_atcPlainText":
            case "YahooMailPlainText":
            case "Ak":
            case "AkaXjCH":
            case "AmAleditableLW-avf":
                p_deliverUrl_cloud = getCloudServiceMsgForText(p_url, c_template_message, cloud_names).replace(/\r\n/g, "<br>");
                break;
            //Zoho TEXT Format :
            case "ze_area":
            case "qx-placeholder-color":
            case "customScrollBar_plain":
            case "_2-s9dD74wgWbEQnHUm6Mog":
                p_deliverUrl_cloud = getCloudServiceMsgForText(p_url, c_template_message, cloud_names);
                break;
        }
        return p_deliverUrl_cloud;
    }

    p_deliverUrl = spliteDeliverUrlFromMixedUrl(p_deliverUrl);
    var argv = p_deliverUrl.split("|");
    var is_certified = parseInt(argv[0]);
    var expire_date = argv[1];
    p_deliverUrl = argv[2];
    var file_name = argv[3];
    var template_message = argv[4];
    var template_download = argv[5];
    var template_download_long = argv[6];
    var template_expires = argv[7];
    var template_hint = argv[8];
    var template_message_plain = template_message.replace("${WINZIP COURIER}", "WinZip Courier");
    var wz_courier = '<a href=http://www.winzip.com/win/en/prodpageec.html style=color:#666666>WinZip Courier</a>';
    var template_message_html = template_message.replace('${WINZIP COURIER}', wz_courier);
    var result = getResultForHtml(template_message_html, template_download, p_deliverUrl, file_name);
    switch(text.replace(/[\s]*/g, "")) {
    case "RichText":
    case "t_mbgct_atcRichText":
    case "HTML":
    case "editableLW-yrriRe":
    case "editableLW-avf":
    case "NewYahooMail":
    case "ze_body":
    case "cke_editablecke_editable_themedcke_contents_ltr":
    case "customScrollBar":
    case "allowTextSelectionConsumerCED":
    case "allowTextSelectioncustomScrollBarowa-font-compose":
    case "_1BD0CHIzklOGMHL1FCsIiW":
        if (expire_date !== ' ') {
            result += template_expires + " " + expire_date + ".<span style=\"font-size:5px\"><br><br></span>";
        }
        if(is_certified) {
            result += "<span>When you retrieve the file, you will be required to log in to ZipSend using your e-mail address as it appears in the \'To\' field. The sender has requested this authentication to ensure that only you can retrieve this file. If you do not have a ZipSend account you can <a href=\"https://zipsend.com/free-trial?sc_cid=zsenddlmsg\" style=\"color:#666666\">create one for free</a>. If you already have a ZipSend account registered to a different e-mail address, please create a new, free ZipSend account for this e-mail address.</span>";
        }
        result = getResultAddHintForHtml(result, template_hint);
        break;
    case "t_mbgct_atcHTML":
        if (expire_date !== ' ') {
            result += template_expires + " " + expire_date + ".<span style=\"font-size:5px\"><br><br></span>";
        }
        if(is_certified) {
            result += "<span>When you retrieve the file, you will be required to log in to ZipSend using your e-mail address as it appears in the \'To\' field. The sender has requested this authentication to ensure that only you can retrieve this file. If you do not have a ZipSend account you can <a href=\"https://zipsend.com/free-trial?sc_cid=zsenddlmsg\" style=\"color:#666666\">create one for free</a>. If you already have a ZipSend account registered to a different e-mail address, please create a new, free ZipSend account for this e-mail address.</span>";
        }
        result = getResultAddHintForHtml(result, template_hint);
        // convert the HTML to escape chars
        result = htmlToEscape(result);
        break;
    case "Ak":
    case "AkaXjCH":
    case "PlainText":
    case "AmAleditableLW-avf":
    case "t_mbgct_atcPlainText":
    case "YahooMailPlainText":
        //Get Result For Text
        result = getResultForText(template_message_plain, template_download_long, file_name, p_deliverUrl, template_expires, expire_date);
        if(is_certified) {
            result += "When you retrieve the file, you will be required to log in to ZipSend using your e-mail address as it appears in the \'To\' field. The sender !has requested this authentication to ensure that only you can retrieve this file. If you do not have a ZipSend account, you can create one for free. If you already have a ZipSend account registered to a different e-mail address, please create a new, free ZipSend account for this e-mail address.<br><br>";
        }
        result = getResultAddHintForText(result, template_hint);
        break;
    case "ze_area":
    case "qx-placeholder-color":
    case "customScrollBar_plain" :
    case "_2-s9dD74wgWbEQnHUm6Mog":
        //Get Result For Zoho Text
        result = getResultForText(template_message_plain, template_download_long, file_name, p_deliverUrl, template_expires, expire_date);
        if(is_certified) {
            result += "When you retrieve the file, you will be required to log in to ZipSend using your e-mail address as it appears in the \'To\' field. The sender !has requested this authentication to ensure that only you can retrieve this file. If you do not have a ZipSend account, you can create one for free. If you already have a ZipSend account registered to a different e-mail address, please create a new, free ZipSend account for this e-mail address.\r\n\r\n";
        }
        result = getResultAddHintForText(result, template_hint).replace(/<br>/g, "\r\n");
        break;
    default:
        result = p_deliverUrl;
    }
    return result;
}

function get_parent_element(p_element, p_n) {
    var parentElement = p_element;
    for(j = 0; j < p_n; j++) {
        parentElement = parentElement.parentNode;
    }
    return parentElement;
}

//************For Gmail New Compose***********************
var NEW_COMPOSE_TEXTAREA_CLASS = 'Am Al editable LW-avf';
var ZIPSEND_TAG = 'ZipSendDeliveryUrlTag';
var GMAIL_NEW_COMPOSE_FORMAT_PLAIN = 'PlainText';
var GMAIL_NEW_COMPOSE_FORMAT_RICH = 'RichText';

function getGmailNewComposeTextAreas() {
    var textAreas = getElementsByClassName(document, NEW_COMPOSE_TEXTAREA_CLASS);
    return textAreas;
}

function taggingZipSendTableForGmail() {
    if(!hasGmailNewComposeTable()) {
        return;
    }
    var indexOfAttachTable = getIndexOfGmailAttachFileTable();
    var temps = getGmailNewComposeTextAreas();
    if (indexOfAttachTable != -1 && temps != null) {
        var insertBody = temps[indexOfAttachTable];
        g_insertBodyPreparedForInsertLink = insertBody;
    }
}

function hasGmailNewComposeTable() {
    var newComposeTextarea = getGmailNewComposeTextAreas();
    if (newComposeTextarea != null && newComposeTextarea.length > 0) {
        return true;
    }
    return false;
}

function getIndexOfGmailAttachFileTable() {
    if (!hasGmailNewComposeTable()) {
        return 0;
    }

    var insert_tools_class = 'wG J-Z-I J-J5-Ji T-I-ax7';
    var tools_folded_class = 'wG J-Z-I J-J5-Ji T-I-ax7';
    var tools_unfolded_class = 'wG J-Z-I J-J5-Ji T-I-ax7 e9';
    var tabsNum = 0;
    var tabsIndex = -1;
    var temps = getElementsByClassName(document, insert_tools_class);
    for(i = 0; i < temps.length; i++) {
        if(temps[i].className == tools_folded_class && temps[i].nodeName == 'DIV') {
            tabsNum += 1;
        }
        if(temps[i].className == tools_unfolded_class && temps[i].style.width != null && temps[i].nodeName == 'DIV') {
            tabsIndex = tabsNum;
            tabsNum += 1;
        }
    }
    return tabsIndex;
}

function getTaggedTextArea() {
    if (typeof(g_insertBodyPreparedForInsertLink) != "undefined") {
        return g_insertBodyPreparedForInsertLink;
    } else {
        return null;
    }
}

function indexOfGmailTaggedTable() {
    var textAreas = getGmailNewComposeTextAreas();
    var taggedTextArea = getTaggedTextArea();
    for (i = 0; i < textAreas.length; i++) {
        if (textAreas[i] == taggedTextArea) {
            return i;
        }
    }
    return -1;
}

function getGmailTextFormatOfIndex(index) {
    var inputs = document.getElementsByTagName('INPUT');
    var isHtml = new Array();
    var inputBody = new Array();
    for (i = 0; i < inputs.length; i++) {
        if (inputs[i].name == 'ishtml') {
            isHtml[isHtml.length] = inputs[i];
        }
        else if (inputs[i].name == 'body') {
            inputBody[inputBody.length] = inputs[i];
        }
    }
    if (inputBody[index] == null || inputBody[index].value == null || inputBody[index].value == '') {
        return;
    }

    if (isHtml[index].value == '1') {
        return GMAIL_NEW_COMPOSE_FORMAT_RICH;
    }
    return GMAIL_NEW_COMPOSE_FORMAT_PLAIN;
}

function getTaggedTableFrame(textArea) {
    var table = textArea;
    var depth = 2;
    while(table) {
        if (table.tagName == 'TABLE') {
            if (depth != 0) {
                depth--;
            } else {
                return table;
            }
        }
        if (!table.parentNode) {
            return;
        }
        table = table.parentNode;
    }
}

function getGmailTextFormatOfTextArea(textArea) {
    var table = getTaggedTableFrame(textArea);
    var superNodeOfModeCheckBox = table.parentNode.parentNode;
    var plain_identify_class = 'J-N J-Ks J-Ks-KO';
    var rich_identify_class = 'J-N J-Ks';
    var isRich = superNodeOfModeCheckBox.getElementsByClassName(rich_identify_class);
    var isPlain = superNodeOfModeCheckBox.getElementsByClassName(plain_identify_class);
    if (isPlain != null && isPlain.length != 0) {
        return GMAIL_NEW_COMPOSE_FORMAT_PLAIN;
    }
    if (isRich != null && isRich.length != 0) {
        return GMAIL_NEW_COMPOSE_FORMAT_RICH;
    }
    return;
}

function getFormatByStateTextValue(textArea) {
    var table = getTaggedTableFrame(textArea);
    var t_span = table.getElementsByTagName('SPAN');
    var span_array = new Array();
    for (i = 0; i < t_span.length; i++) {
        if (t_span[i].parentNode.tagName == 'DIV' && t_span[i].className == 'oG') {
            span_array[span_array.length] = t_span[i];
        }
    }
    if (span_array.length != 1) {
        return;
    }
    if (!span_array[0].hasChildNodes()) {
        return GMAIL_NEW_COMPOSE_FORMAT_RICH;
    } else {
        var state_text = span_array[0].firstChild.data;
        if (state_text && state_text != '') {
            return GMAIL_NEW_COMPOSE_FORMAT_PLAIN;
        }
    }
}

function getGmailTextFormat(taggedAreaIndex, taggedArea) {
    var format = getGmailTextFormatOfTextArea(taggedArea);
    if (format != null && format != '') {
        return format;
    }
    format = getGmailTextFormatOfIndex(taggedAreaIndex);
    if (format != null && format != '') {
        return format;
    }
    format = getFormatByStateTextValue(taggedArea);
    if (format != null && format != '') {
        return format;
    }
    return null;
}

function zipsendInsertDeliveryUrlForGmailNewCompose(p_deliveryUrl) {
    if (!hasGmailNewComposeTable()) {
        return;
    }
    var taggedAreaIndex = 1;
    var textAreas = getGmailNewComposeTextAreas();
    var body = textAreas[0];
    for (var i = 0; i < textAreas.length; i++) {
        if (textAreas[i].parentElement.className == "Ar Au Ao") {
            body = textAreas[i];
            taggedAreaIndex = i + 1;
            break;
        }
    }
    var textFormat = getGmailTextFormat(taggedAreaIndex, body);
    if (textFormat == null) { // When the user did not click the more option button, we could not judge the text model, so we simulated the more option click event.
        var evt = document.createEvent("MouseEvents");
        evt.initEvent("mousedown", true, true);
        var moreOption = document.getElementsByClassName("J-JN-M-I J-J5-Ji Xv L3 T-I-ax7 T-I")[0];
        moreOption.dispatchEvent(evt);
        moreOption.dispatchEvent(evt);
        textFormat = getGmailTextFormat(taggedAreaIndex, body);
    }
    if (textFormat == null) {
        textFormat = GMAIL_NEW_COMPOSE_FORMAT_RICH;
    }
    var deliverUrl = getFormatDeliverUrl(p_deliveryUrl, textFormat);
    body.innerHTML = deliverUrl + body.innerHTML;
}

function tryInsertGmailTargetTextArea(p_deliveryUrl, count) {
    if (count > 10) {
        return;
    }

    var taggedAreaIndex;
    var body;
    var textArea = getGmailNewComposeTextAreas();
    if (textArea != null) {
        if (textArea.length == 1) {
            body = textArea[0];
            taggedAreaIndex = 0;
        }
        else {
            var currentHtml = 'Ar Au Ao';
            for (var i = 0; i < textArea.length; i++) {
                if (textArea[i].parentNode.className == currentHtml) {
                    body = textArea[i];
                    taggedAreaIndex = i;
                }
            }
        }
    }

    if (body != null) {
        var textFormat = getGmailTextFormat(taggedAreaIndex, body);
        var deliverUrl = getFormatDeliverUrl(p_deliveryUrl, textFormat);
        body.innerHTML = deliverUrl + body.innerHTML;
    }
    else {
        setTimeout(tryInsertGmailTargetTextArea, 500, p_deliveryUrl, count + 1);
    }
}

function excuteJavaScript(script, nativeCallbackId) {
    var ret;
    try {
        ret = eval(script);
    } catch(e) {
        ret = null;
    }
    chrome.runtime.sendMessage({result:ret, callbackId:nativeCallbackId});
}

function htmlToEscape(str) {
    return String(str)
     .replace(/&/g, '&amp;')
     .replace(/"/g, '&quot;')
     .replace(/'/g, '&#39;')
     .replace(/</g, '&lt;')
     .replace(/>/g, '&gt;');
}

function doStuff(message, sender, sendResponse){
        var functionName = message["function"];
        var paramArray = message["params"];
        if (functionName != null && paramArray != null) {
            if("zipsendInsertDeliveryUrl" == functionName && paramArray.length == 2) {
                zipsendInsertDeliveryUrl(paramArray[0], paramArray[1]);
            } else if ("taggingZipSendTableForGmail" == functionName) {
                taggingZipSendTableForGmail();
            } else if ("excuteJavaScript" == functionName && paramArray.length == 2) {
                script = paramArray[0];
                var ret;
                try {
                    if (script.includes("tr_image-dialog-your-images-tab-content"))
                        ret = document.getElementById("tr_image-dialog-your-images-tab-content") != null;
                    else
                        ret = eval(script);
                } catch(e) {
                    console.log("excuteJavaScript exception: " + e);
                    ret = null;
                }
                sendResponse({result: ret, callbackId: paramArray[1]});
            }
        }
}

(function() {
    chrome.runtime.onMessage.addListener(doStuff);
})();
