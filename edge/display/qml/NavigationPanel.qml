import QtQuick 2.12

Rectangle {
    id: panel
    color: "#07141d"
    signal closed()
    property var info: ({})
    property bool busy: false
    property bool polling: false
    property bool maintenance: false
    property string selected: ""
    property string selectedLabel: ""
    property string message: "只查询状态，不会自动启动运动。"

    function poll() {
        if (polling) return
        polling = true
        var r = new XMLHttpRequest()
        r.onreadystatechange = function() {
            if (r.readyState !== XMLHttpRequest.DONE) return
            polling = false
            try { info = r.status === 200 ? JSON.parse(r.responseText) : {} }
            catch (e) { info = {} }
        }
        r.open("GET", "http://127.0.0.1:8765/api/navigation/status")
        r.send()
    }
    function submit() {
        if (busy || !selected) return
        busy = true
        var r = new XMLHttpRequest()
        r.onreadystatechange = function() {
            if (r.readyState !== XMLHttpRequest.DONE) return
            busy = false
            selected = ""
            try { message = JSON.parse(r.responseText).message || "请求未完成，请查询状态。" }
            catch (e) { message = "请求结果不确定，请先查看状态，不要重复启动。" }
            poll()
        }
        r.open("POST", "http://127.0.0.1:8765/api/navigation/command")
        r.setRequestHeader("Content-Type", "application/json")
        r.setRequestHeader("X-LuckRobot-Display", "1")
        r.send(JSON.stringify({command: selected, confirmed: true}))
    }
    onVisibleChanged: { selected = ""; if (visible) poll() }
    Timer { interval: 1000; repeat: true; running: panel.visible; onTriggered: panel.poll() }
    MouseArea { anchors.fill: parent }
    Flickable {
        anchors.fill: parent; clip: true
        contentWidth: width; contentHeight: controls.height + 90
    Column {
        id: controls
        x: 45; y: 45; width: parent.width - 90; spacing: 22
        Text { text: "底盘建图与导航"; font.pixelSize: 32; color: "#ffffff" }
        Text {
            width: parent.width; wrapMode: Text.Wrap
            font.pixelSize: 25; color: panel.info.fresh ? "#65dabd" : "#ed9b80"
            text: "小脑软件：" + (panel.info.system ? panel.info.system.state || "未连接" : "未连接") +
                  "  /  " + (panel.info.fresh ? "底盘：" : "底盘未就绪：") + (panel.info.state || "UNAVAILABLE")
        }
        Text {
            width: parent.width; wrapMode: Text.Wrap; font.pixelSize: 21; color: "#c4d2de"
            text: "原因：" + (panel.info.reason || panel.info.error || "暂无") +
                  "\n地图版本：" + (panel.info.map ? panel.info.map.map_id : "暂无") +
                  "\n导航就绪：" + (panel.info.navigation_ready ? "是（含完整地图）" : "尚未确认") +
                  (panel.info.task ? "\n任务：" + panel.info.task.command + " / " + panel.info.task.status + "  " + panel.info.task.message : "")
        }
        Text {
            width: parent.width; wrapMode: Text.Wrap; font.pixelSize: 19; color: "#bcc4cf"
            text: "当前接入 ROS 模式控制，Nav2目标阶段尚未启用。自动建图/恢复探索会运动，确认前请检查现场。暂停不是急停；断网不代表停车。"
        }
        Flow {
            width: parent.width; spacing: 18
            Repeater {
                model: [
                    {label: "查询状态", cmd: "status"},
                    {label: "启动小脑软件", cmd: "start"}, {label: "结束小脑软件", cmd: "stop"},
                    {label: "手动建图", cmd: "manual_mapping"}, {label: "自动建图", cmd: "auto_mapping"},
                    {label: "暂停流程", cmd: "pause"}, {label: "恢复流程", cmd: "resume"},
                    {label: "取消流程", cmd: "cancel"}]
                delegate: NetworkButton {
                    width: 165; height: 62
                    text: modelData.label
                    enabled: !!panel.info.system && panel.info.system.fresh === true && !panel.busy
                    selected: panel.selected === modelData.cmd
                    onClicked: {
                        if (modelData.cmd === "status") { panel.poll(); panel.message = "正在刷新状态。"; return }
                        panel.selected = modelData.cmd
                        panel.selectedLabel = modelData.label
                        panel.message = modelData.cmd === "resume" ? "恢复建图将开始自动探索；继续手动建图请选择手动建图。" :
                            modelData.cmd === "finish_mapping" ? "确认建图覆盖范围已满足要求后再执行。" :
                            "请确认执行“" + modelData.label + "”；请求受理不代表完成。"
                    }
                }
            }
        }
        Text {
            text: panel.maintenance ? "收起地图与维护 ▴" : "地图与维护 ▾"; color: "#7e909f"; font.pixelSize: 17
            height: 38; width: 160; verticalAlignment: Text.AlignVCenter
            MouseArea { anchors.fill: parent; onClicked: panel.maintenance = !panel.maintenance }
        }
        Flow {
            width: parent.width
            visible: panel.maintenance; spacing: 12
            Repeater {
                model: [{label: "完成手动建图", cmd: "finish_mapping"}, {label: "加载已有地图", cmd: "load_latest"}, {label: "重启小脑软件", cmd: "restart"},
                        {label: "已核对未知结果", cmd: "acknowledge_unknown"}]
                delegate: NetworkButton {
                    width: 200; height: 52; text: modelData.label
                    enabled: !panel.busy
                    onClicked: {
                        panel.selected = modelData.cmd
                        panel.selectedLabel = modelData.label
                        panel.message = modelData.cmd === "finish_mapping" ? "仅用于手动建图完成后确认保存；自动建图成功会自动保存并进入定位。" :
                            modelData.cmd === "load_latest" ? "用于启动后加载已有地图；自动建图成功后不需要再加载，可能需要设置初始位姿。" :
                            "确认“" + modelData.label + "”？重启不会恢复旧任务。核对未知结果不会重发任务。"
                    }
                }
            }
        }
        Text { width: parent.width; wrapMode: Text.Wrap; font.pixelSize: 22; color: "#ffffff"; text: panel.message }
        Row {
            spacing: 20
            NetworkButton { width: 210; height: 60; text: panel.busy ? "请求处理中" : "确认执行"; enabled: !panel.busy && !!panel.selected && !!panel.info.system && panel.info.system.fresh === true; onClicked: panel.submit() }
            NetworkButton { width: 160; height: 60; text: "关闭"; onClicked: panel.closed() }
        }
    }
    }
}
