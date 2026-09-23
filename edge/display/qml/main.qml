import QtQuick 2.12
import QtQuick.Window 2.12

Window {
    id: root
    visible: true
    visibility: Window.FullScreen
    color: "#03080f"
    title: "LuckRobot"

    property string robotState: "sleeping"
    property string stateLabel: "等待 Lucky"
    property string userText: ""
    property string assistantText: ""
    property bool blinking: false
    property bool connected: true

    function accent() {
        if (robotState === "listening") return "#52ffd2"
        if (robotState === "interrupted") return "#ff9a7a"
        if (robotState === "music") return "#b98cff"
        return "#66e6ff"
    }
    function symbol() {
        if (robotState === "sleeping") return "Z z"
        if (robotState === "listening") return "◉"
        if (robotState === "transcribing") return "…"
        if (robotState === "thinking") return "✦"
        if (robotState === "speaking") return ")))"
        if (robotState === "interrupted") return "⚡"
        if (robotState === "music") return "♫"
        return "●"
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#102b3b" }
            GradientStop { position: 0.48; color: "#07111d" }
            GradientStop { position: 1.0; color: "#02050a" }
        }
    }
    Text {
        anchors { top: parent.top; right: parent.right; margins: root.height * 0.045 }
        text: root.symbol(); color: root.accent(); font.bold: true
        font.pixelSize: Math.max(30, root.height * 0.075)
    }
    Text {
        anchors { top: parent.top; left: parent.left; margins: 20 }
        text: "状态连接中…"; color: "#ffb5b5"; opacity: root.connected ? 0 : 1
        font.pixelSize: Math.max(16, root.height * 0.025)
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }

    Rectangle {
        id: face
        width: Math.min(root.width * 0.62, root.height * 0.78)
        height: width / 1.45
        anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: root.height * 0.08 }
        radius: width * 0.22; color: "#d90a1724"
        border.width: Math.max(2, root.height * 0.003); border.color: root.accent()
        opacity: root.robotState === "sleeping" ? 0.63 : 1
        scale: root.robotState === "sleeping" ? 0.96 : 1
        Behavior on border.color { ColorAnimation { duration: 250 } }
        Behavior on opacity { NumberAnimation { duration: 300 } }
        Behavior on scale { NumberAnimation { duration: 300 } }

        Rectangle {
            id: leftEye
            width: face.width * 0.25
            height: root.blinking || root.robotState === "sleeping" ? face.height * 0.025 : face.height * 0.20
            x: face.width * 0.14
            y: face.height * (root.robotState === "thinking" ? 0.25 : 0.30)
            radius: height / 2; color: root.accent()
            Behavior on height { NumberAnimation { duration: 90 } }
            Behavior on y { NumberAnimation { duration: 240 } }
        }
        Rectangle {
            id: rightEye
            width: leftEye.width; height: leftEye.height; x: face.width * 0.61
            y: face.height * (root.robotState === "thinking" ? 0.36 : 0.30)
            radius: height / 2; color: root.accent()
            Behavior on height { NumberAnimation { duration: 90 } }
            Behavior on y { NumberAnimation { duration: 240 } }
        }
        Rectangle {
            width: face.width * (root.robotState === "music" ? 0.24 : 0.19)
            height: speakingAnimation.running ? face.height * 0.11 : face.height * 0.025
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: face.height * 0.68 }
            radius: height / 2; color: "transparent"
            border.width: Math.max(3, face.height * 0.018); border.color: root.accent()
            SequentialAnimation on scale {
                id: speakingAnimation
                running: root.robotState === "speaking" || root.robotState === "music"
                loops: Animation.Infinite
                NumberAnimation { to: 0.62; duration: root.robotState === "music" ? 260 : 130 }
                NumberAnimation { to: 1.18; duration: root.robotState === "music" ? 260 : 130 }
            }
        }
    }

    Column {
        width: root.width * 0.90; spacing: root.height * 0.012
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: root.height * 0.045 }
        Text {
            width: parent.width; horizontalAlignment: Text.AlignHCenter
            text: root.stateLabel.toUpperCase(); color: root.accent(); font.bold: true
            font.pixelSize: Math.max(18, root.height * 0.032); font.letterSpacing: 2
        }
        Text {
            width: parent.width; horizontalAlignment: Text.AlignHCenter
            text: root.userText ? "你：" + root.userText : ""; color: "#8ba8bb"
            font.pixelSize: Math.max(16, root.height * 0.028); elide: Text.ElideRight
        }
        Text {
            width: parent.width; horizontalAlignment: Text.AlignHCenter
            text: root.assistantText; color: "#effcff"; font.bold: true
            font.pixelSize: Math.max(21, root.height * 0.043); elide: Text.ElideRight
        }
    }

    Timer {
        interval: 5200; repeat: true; running: root.robotState !== "sleeping"
        onTriggered: { root.blinking = true; closeBlink.start() }
    }
    Timer { id: closeBlink; interval: 130; onTriggered: root.blinking = false }
    Timer {
        interval: 250; repeat: true; running: true; triggeredOnStart: true
        onTriggered: {
            var request = new XMLHttpRequest()
            request.onreadystatechange = function() {
                if (request.readyState !== XMLHttpRequest.DONE) return
                if (request.status !== 200) { root.connected = false; return }
                try {
                    var value = JSON.parse(request.responseText)
                    root.robotState = value.state || "sleeping"
                    root.stateLabel = value.label || root.robotState
                    root.userText = value.user_text || ""
                    root.assistantText = value.assistant_text || ""
                    root.connected = true
                } catch (error) { root.connected = false }
            }
            request.open("GET", "http://127.0.0.1:8765/api/state")
            request.send()
        }
    }
}
