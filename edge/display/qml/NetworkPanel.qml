import QtQuick 2.12
Rectangle {
    id: panel
    color: "#07171f"
    property var devices: ({})
    property var networks: []
    property var tokens: ({})
    property var editor: null
    property bool shift: false
    property bool symbols: false
    property bool both: true
    property bool brainStatic: false
    property bool peerStatic: false
    property bool busy: false
    property bool statusBusy: false
    property bool jobBusy: false
    property bool scanning: false
    property string jobId: ""
    property string security: "wpa-psk"
    property string message: "默认 DHCP；有线 10.0.0.50 ↔ 10.0.0.51 保持不变"
    signal closed()

    function api(path, body, done) {
        var r = new XMLHttpRequest()
        r.onreadystatechange = function() {
            if (r.readyState !== XMLHttpRequest.DONE) return
            var value = null
            try { value = JSON.parse(r.responseText) } catch (e) {}
            done(r.status >= 200 && r.status < 300, value)
        }
        r.open(body === null ? "GET" : "POST", "http://127.0.0.1:8765/api/network/" + path)
        if (body !== null) {
            r.setRequestHeader("X-LuckRobot-Display", "1")
            r.setRequestHeader("Content-Type", "application/json")
        }
        r.send(body === null ? "" : JSON.stringify(body))
    }
    function explain(result) {
        if (!result) return "服务无响应"
        if (result.ok) return result.state === "confirmed" ? "已保存" : (result.state === "rolled_back" ? "已恢复" : "连接成功，等待确认")
        var errors = {"peer_not_paired":"尚未配对", "peer_unreachable":"有线连接不可达", "helper_unavailable":"网络服务不可用",
            "preflight_failed":"设备不可用或有待确认操作", "pair_failed_rolled_back":"另一台失败，本机已回退", "rollback_pending_timeout":"等待超时自动回退",
            "confirmation_expired":"确认已超时，已回退", "invalid_password":"密码格式不正确", "RuntimeError":"连接失败，请检查密码和信号"}
        return errors[result.error] || "操作失败，请检查网络参数"
    }
    function refresh() {
        if (statusBusy) return
        statusBusy = true
        api("status", null, function(ok, data) {
            statusBusy = false
            if (!ok || !data) { message = "网络状态服务不可用"; return }
            devices = data
            var pending = {}
            for (var t in data) if (data[t].pending) pending[t] = data[t].pending.token
            tokens = pending
        })
    }
    function deviceText(target, title) {
        var d = devices[target]
        if (!d || !d.ok) return title + "：" + explain(d)
        var lines = [title + " · " + d.hostname]
        for (var i = 0; i < d.interfaces.length; i++) {
            var it = d.interfaces[i]
            lines.push((it.name === d.wifi_interface ? "Wi-Fi " : "有线 ") + (it.addresses.join("，") || "未连接"))
        }
        return lines.join("\n")
    }
    function scan() {
        if (scanning) return
        scanning = true
        api("action", {action:"scan", target:"brain"}, function(ok, data) {
            scanning = false
            if (ok && data && data.ok) networks = data.networks
            else message = explain(data)
        })
    }
    function focusEditor(item) {
        editor = item
        var point = item.mapToItem(form.contentItem, 0, 0)
        if (point.y + 50 > form.contentY + form.height) form.contentY = Math.max(0, point.y + 60 - form.height)
    }
    function makeConfig(manual, address) {
        return {ssid:ssid.text, password:password.text, security:security,
                method:manual ? "manual" : "auto", address:address,
                gateway:gateway.text.trim(), dns:dns.text.split(/[,，;；\s]+/).filter(function(x) {return x.length > 0})}
    }
    function apply() {
        var configs = {brain:makeConfig(brainStatic, brainAddress.text.trim())}
        if (both) configs.cerebellum = makeConfig(peerStatic, peerAddress.text.trim())
        busy = true; editor = null
        message = "正在连接；请勿关闭电源。成功后须在 3 分钟内确认，否则自动回退。"
        api("action", {action:"apply", configs:configs}, function(ok, data) {
            password.text = ""
            if (ok && data && data.id) jobId = data.id
            else { busy = false; message = "未提交：请检查密码、IP/前缀、网关和 DNS；两台不能使用相同 IP。" }
        })
    }
    function finish(action) {
        busy = true
        api("action", {action:action, tokens:tokens}, function(ok, data) {
            busy = false
            if (!ok || !data) { message = "操作未确认，未保存的配置将自动回退"; return }
            message = ""
            for (var t in data) message += (t === "brain" ? "大脑：" : "小脑：") + explain(data[t]) + "  "
            refresh()
        })
    }
    onVisibleChanged: {
        if (visible) { refresh(); scan() }
        else { password.text = ""; editor = null }
    }
    Timer {
        interval: 3000; repeat: true; running: panel.visible
        onTriggered: {
            panel.refresh()
            if (!jobId || jobBusy) return
            jobBusy = true
            panel.api("job", null, function(ok, data) {
                jobBusy = false
                if (ok && data && data.id === jobId && data.state === "done") {
                    busy = false; jobId = ""; message = ""
                    for (var t in data.results) message += (t === "brain" ? "大脑：" : "小脑：") + explain(data.results[t]) + "  "
                    refresh()
                }
            })
        }
    }
    Text { x:24; y:16; text:"设备网络"; color:"#e7fff8"; font.pixelSize:30 }
    NetworkButton { anchors.right:parent.right; anchors.top:parent.top; anchors.margins:14; text:"关闭"; onClicked:panel.closed() }
    Row {
        x:24; y:64; spacing:24
        Repeater {
            model:["brain", "cerebellum"]
            Text { width:(panel.width - 72) / 2; height:85; text:panel.deviceText(modelData, modelData === "brain" ? "大脑" : "小脑"); color:"#b4e8dd"; font.pixelSize:18; wrapMode:Text.Wrap }
        }
    }
    Item {
        x:24; y:158; width:panel.width - 48
        height:panel.height - y - footer.height - keyboard.height - 20
        Column {
            width:parent.width * 0.40; height:parent.height; spacing:8
            NetworkButton { width:parent.width; text:scanning ? "扫描中…" : "刷新 Wi-Fi 列表"; enabled:!scanning && !busy; onClicked:panel.scan() }
            ListView {
                width:parent.width; height:parent.height - 54; clip:true; spacing:6; model:panel.networks
                delegate: Rectangle {
                    width:ListView.view.width; height:66; radius:8; color:ssid.text === modelData.ssid ? "#195a55" : "#132c37"
                    Text { anchors.fill:parent; anchors.margins:10; text:modelData.ssid + "\n" + modelData.security + " · " + modelData.signal + "%"; color:"white"; font.pixelSize:17; elide:Text.ElideRight }
                    MouseArea { anchors.fill:parent; enabled:!busy; onClicked: {
                        if (/802.1X|EAP/.test(modelData.security)) { message = "暂不支持企业认证 Wi-Fi"; return }
                        ssid.text = modelData.ssid
                        security = modelData.security === "--" || !modelData.security ? "open" : (/WPA3/.test(modelData.security) && !/WPA2/.test(modelData.security) ? "sae" : "wpa-psk")
                        password.text = ""
                    } }
                }
            }
        }
        Flickable {
            id:form; x:parent.width * 0.44; width:parent.width * 0.56; height:parent.height
            contentHeight:fields.height + 20; clip:true; boundsBehavior:Flickable.StopAtBounds
            Column {
                id:fields; width:form.width; spacing:8; enabled:!busy
                NetworkField { id:ssid; width:parent.width; label:"Wi-Fi 名称（可点选左侧）"; onEditing:panel.focusEditor(editor) }
                NetworkField { id:password; width:parent.width; label:security === "open" ? "开放网络，无需密码" : "Wi-Fi 密码"; secret:true; enabled:security !== "open"; onEditing:panel.focusEditor(editor) }
                NetworkButton { width:parent.width; selected:both; text:both ? "✓ 同时配置小脑" : "仅配置大脑"; onClicked:both = !both }
                NetworkButton { width:parent.width; text:brainStatic ? "大脑：手动 IPv4" : "大脑：自动 DHCP"; onClicked:brainStatic = !brainStatic }
                NetworkField { id:brainAddress; width:parent.width; visible:brainStatic; height:visible ? 66 : 0; label:"大脑 IP/前缀，例如 192.168.3.23/24"; onEditing:panel.focusEditor(editor) }
                NetworkButton { width:parent.width; visible:both; height:visible ? 46 : 0; text:peerStatic ? "小脑：手动 IPv4" : "小脑：自动 DHCP"; onClicked:peerStatic = !peerStatic }
                NetworkField { id:peerAddress; width:parent.width; visible:both && peerStatic; height:visible ? 66 : 0; label:"小脑 IP/前缀，例如 192.168.3.32/24"; onEditing:panel.focusEditor(editor) }
                NetworkField { id:gateway; width:parent.width; visible:brainStatic || (both && peerStatic); height:visible ? 66 : 0; label:"网关，例如 192.168.3.1"; onEditing:panel.focusEditor(editor) }
                NetworkField { id:dns; width:parent.width; visible:gateway.visible; height:visible ? 66 : 0; label:"DNS，例如 223.5.5.5,1.1.1.1"; onEditing:panel.focusEditor(editor) }
            }
        }
    }
    Column {
        id:footer; anchors.left:parent.left; anchors.right:parent.right; anchors.bottom:keyboard.top; anchors.margins:20; spacing:8
        Text { width:parent.width; text:panel.message; color:"#d7e9b0"; font.pixelSize:17; wrapMode:Text.Wrap }
        Row {
            spacing:12
            NetworkButton { text:busy ? "处理中…" : "连接 Wi-Fi"; enabled:!busy && Object.keys(tokens).length === 0; onClicked:panel.apply() }
            NetworkButton { width:180; text:"确认保留连接"; enabled:!busy && Object.keys(tokens).length > 0; selected:enabled; onClicked:panel.finish("confirm") }
            NetworkButton { text:"恢复原配置"; enabled:!busy && Object.keys(tokens).length > 0; onClicked:panel.finish("rollback") }
        }
    }
    Rectangle {
        id:keyboard; anchors.bottom:parent.bottom; width:parent.width; height:editor ? Math.min(240, panel.height * 0.32) : 0; visible:height > 0; color:"#0d2631"
        Column {
            anchors.fill:parent; anchors.margins:5; spacing:4
            Repeater {
                model:panel.symbols ? ["1234567890", "!@#$%^&*()", "-_=+[]{}\\|", ";:'\",.<>/?"] : ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm.-_"]
                Row {
                    anchors.horizontalCenter:parent.horizontalCenter; spacing:4
                    property string rowText:modelData
                    Repeater {
                        model:parent.rowText.split("")
                        NetworkButton { width:(panel.width - 60)/11; height:(keyboard.height - 30)/5; text:panel.shift ? modelData.toUpperCase() : modelData; onClicked:if (panel.editor) panel.editor.insert(panel.editor.cursorPosition, text) }
                    }
                }
            }
            Row {
                anchors.horizontalCenter:parent.horizontalCenter; spacing:8
                NetworkButton { width:100; height:(keyboard.height - 30)/5; text:"大小写"; selected:shift; onClicked:shift = !shift }
                NetworkButton { width:100; height:(keyboard.height - 30)/5; text:"符号"; selected:symbols; onClicked:symbols = !symbols }
                NetworkButton { width:180; height:(keyboard.height - 30)/5; text:"空格"; onClicked:if (editor) editor.insert(editor.cursorPosition, " ") }
                NetworkButton { width:100; height:(keyboard.height - 30)/5; text:"退格"; onClicked:if (editor && editor.cursorPosition > 0) editor.remove(editor.cursorPosition - 1, editor.cursorPosition) }
                NetworkButton { width:100; height:(keyboard.height - 30)/5; text:"完成"; onClicked:editor = null }
            }
        }
    }
}
