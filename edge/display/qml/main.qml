import QtQuick 2.12
import QtQuick.Window 2.12

Window {
    id: root
    visible: true
    visibility: Window.FullScreen
    color: "#03080f"
    title: "LuckRobot"

    property string robotState: "sleeping"
    property bool voicePlaying: false
    property string stateLabel: "等待 Lucky"
    property string userText: ""
    property string assistantText: ""
    property var assistantLines: []
    property int assistantLineIndex: 0
    property var musicInfo: null
    property string musicSignature: ""
    property var musicLyrics: []
    property string musicLyricSignature: ""
    property int musicLyricIndex: 0
    property bool blinking: false
    onBlinkingChanged: demonFace.requestPaint()
    property bool eyesAsleep: true
    property bool wakeHolding: false
    property real eyeOpen: 0
    onEyeOpenChanged: demonFace.requestPaint()
    Behavior on eyeOpen { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
    property real wakeTrail: 0
    onWakeTrailChanged: demonFace.requestPaint()
    onRobotStateChanged: {
        if (root.robotState !== "sleeping" && root.robotState !== "music" && root.eyesAsleep) {
            root.eyesAsleep = false
            root.wakeHolding = true
            root.blinking = false
            root.gaze = 0
            root.gazeY = 0
            root.wakeTrail = 0
            wakeTrailExpand.restart()
            wakeOpenDelay.restart()
            wakeHoldDone.restart()
        }
    }
    property real gaze: 0
    property real gazeY: 0
    Behavior on gaze { NumberAnimation { duration: 900; easing.type: Easing.InOutQuad } }
    Behavior on gazeY { NumberAnimation { duration: 900; easing.type: Easing.InOutQuad } }
    property int gazeStep: 0
    property real glowPhase: 0
    property var lightInfo: ({"on": true, "mode": "breath", "rgb": [255, 0, 0]})
    function eyeColor() {
        if (lightInfo.on === false) return "#3d4652"
        if (lightInfo.mode === "rainbow") {
            var palette = ["#ff3048", "#ff9a27", "#f6e34a", "#32ecae", "#36c7ff", "#a371ff"]
            return palette[Math.floor(glowPhase / 8) % palette.length]
        }
        var rgb = lightInfo.rgb || [255, 0, 0]
        return Qt.rgba(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1)
    }
    property bool connected: true
    property string qqAuthState: "unknown"
    property string qqAuthDetail: ""
    property string qqNickname: ""
    property bool qqHasAvatar: false
    property bool qqAuthOpen: false
    property int qqQrRevision: 0
    property int qqAvatarRevision: 0
    property int qqBrowserRevision: 0
    property int qqBrowserSlot: 0
    property bool qqQrAvailable: false
    property int qqQrToken: 0
    property bool qqSwitchPending: false
    property bool musicControlPending: false
    property string musicControlRequestId: ""

    function musicIsPlaying() {
        return !musicInfo || musicInfo.playing !== false
    }

    function requestMusicControl(action) {
        if (musicControlPending) return
        musicControlPending = true
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            if (request.status >= 200 && request.status < 300) {
                try {
                    root.musicControlRequestId = JSON.parse(request.responseText).id || ""
                    if (!root.musicControlRequestId) root.musicControlPending = false
                }
                catch (error) { root.musicControlPending = false }
            } else {
                root.musicControlPending = false
                console.warn("Music control request failed: " + action + " HTTP " + request.status)
            }
        }
        request.open("POST", "http://127.0.0.1:8765/api/music/control")
        request.setRequestHeader("X-LuckRobot-Display", "1")
        request.setRequestHeader("Content-Type", "application/json")
        request.send(JSON.stringify({action: action}))
    }

    Timer {
        interval: 350; repeat: true; running: root.musicControlPending && !!root.musicControlRequestId
        onTriggered: {
            var request = new XMLHttpRequest()
            request.onreadystatechange = function() {
                if (request.readyState !== XMLHttpRequest.DONE || request.status !== 200) return
                try {
                    var result = JSON.parse(request.responseText)
                    if (result.id === root.musicControlRequestId) {
                        root.musicControlPending = false
                        root.musicControlRequestId = ""
                        if (!result.ok) console.warn("Music control failed: " + result.message)
                    }
                } catch (error) {}
            }
            request.open("GET", "http://127.0.0.1:8765/api/music/control")
            request.send()
        }
    }

    function requestQqLogin() {
        qqAuthOpen = true
        qqAuthState = "starting"
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            if (request.status < 200 || request.status >= 300) {
                root.qqAuthState = "error"
                root.qqAuthDetail = "登录请求未到达服务，请检查机器人程序"
            }
        }
        request.open("POST", "http://127.0.0.1:8765/api/music/auth/login")
        request.setRequestHeader("X-LuckRobot-Display", "1")
        request.send()
    }

    function requestQqLogout(switchUser) {
        qqSwitchPending = switchUser
        qqAuthState = "logging_out"
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            if (request.status < 200 || request.status >= 300) {
                root.qqSwitchPending = false
                root.qqAuthState = "error"
                root.qqAuthDetail = "退出登录请求失败"
            }
        }
        request.open("POST", "http://127.0.0.1:8765/api/music/auth/logout")
        request.setRequestHeader("X-LuckRobot-Display", "1")
        request.send()
    }

    function clickQqBrowser(x, y) {
        var request = new XMLHttpRequest()
        request.open("POST", "http://127.0.0.1:8765/api/music/auth/browser/click")
        request.setRequestHeader("X-LuckRobot-Display", "1")
        request.setRequestHeader("Content-Type", "application/json")
        request.send(JSON.stringify({x: x, y: y}))
    }

    function closeQqPanel() {
        if (root.qqAuthState === "browser") {
            var request = new XMLHttpRequest()
            request.open("POST", "http://127.0.0.1:8765/api/music/auth/browser/cancel")
            request.setRequestHeader("X-LuckRobot-Display", "1")
            request.send()
        }
        root.qqAuthOpen = false
    }

    function accent() {
        if (robotState === "listening") return "#52ffd2"
        if (robotState === "interrupted") return "#ff9a7a"
        if (robotState === "music") return "#31d687"
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
    function musicTitle() {
        return musicInfo && musicInfo.title ? musicInfo.title : "正在播放音乐"
    }
    function musicArtists() {
        return musicInfo && musicInfo.artists ? musicInfo.artists.join(" · ") : ""
    }

    function musicCover() {
        return musicInfo && musicInfo.cover_revision ?
            "http://127.0.0.1:8765/api/music/cover?v=" + musicInfo.cover_revision : ""
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: root.robotState === "music" ? "#0d3828" : "#102b3b" }
            GradientStop { position: 0.48; color: root.robotState === "music" ? "#08241c" : "#07111d" }
            GradientStop { position: 1.0; color: root.robotState === "music" ? "#03120f" : "#02050a" }
        }
    }

    Text {
        visible: root.robotState === "music"
        anchors { top: parent.top; right: parent.right; margins: root.height * 0.045 }
        text: root.symbol(); color: root.accent(); font.bold: true
        font.pixelSize: Math.max(30, root.height * 0.075)
    }
    Text {
        visible: root.robotState === "music"
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 20 }
        text: "状态连接中…"; color: "#ffb5b5"; opacity: root.connected ? 0 : 1
        font.pixelSize: Math.max(16, root.height * 0.025)
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }

    Rectangle {
        id: face
        visible: root.robotState !== "music"
        anchors.fill: parent
        color: "#050408"

        Canvas {
            id: demonFace
            anchors.fill: parent
            onPaint: {
                var c = getContext("2d"), w = width, h = height
                c.clearRect(0, 0, w, h)
                var color = root.eyeColor()
                var shut = root.blinking || root.eyeOpen < 0.02
                var pulse = root.lightInfo.mode === "breath" ? 0.72 + 0.18 * Math.sin(root.glowPhase * 0.14) : 0.9
                if (root.lightInfo.on === false) pulse = 0.25
                for (var side = 0; side < 2; side++) {
                    var x = side === 0 ? w * 0.045 : w * 0.535
                    var y = h * 0.28, ew = w * 0.42
                    var eh = root.blinking ? h * 0.008 : h * (0.008 + root.eyeOpen * 0.222)
                    var cx = x + ew * 0.5, cy = y + eh * 0.45
                    c.save()
                    c.translate(cx, cy)
                    c.rotate(side === 0 ? 0.25 : -0.13)
                    c.translate(-cx, -cy)
                    c.beginPath()
                    c.moveTo(x, y + eh * 0.10)
                    c.lineTo(x + ew, y - eh * 0.12)
                    c.quadraticCurveTo(x + ew * 0.85, y + eh * 0.92, x + ew * 0.43, y + eh)
                    c.quadraticCurveTo(x + ew * 0.09, y + eh * 0.90, x, y + eh * 0.10)
                    c.closePath()
                    c.globalAlpha = shut ? pulse : 1
                    c.fillStyle = shut ? color : "#f9fbff"; c.fill()
                    c.strokeStyle = color
                    for (var glowStep = 0; glowStep < 32; glowStep++) {
                        var edge = glowStep / 31
                        c.globalAlpha = pulse * (0.020 + edge * 0.022)
                        c.lineWidth = Math.max(4, h * (0.080 - edge * 0.073))
                        c.stroke()
                    }
                    if (!shut) {
                        c.globalAlpha = 0.38
                        c.lineWidth = Math.max(4, h * 0.010)
                        c.strokeStyle = "#ffe3e6"; c.stroke()
                    }
                    if (!shut) {
                        var lookX = root.robotState === "speaking" ? 0 : root.gaze
                        var lookY = root.robotState === "speaking" ? 0 : root.gazeY
                        var px = x + ew * (0.52 + lookX * 0.20)
                        var py = y + eh * (0.38 + lookY * 0.13)
                        c.globalAlpha = 1
                        var pupilShade = c.createRadialGradient(px, py, ew * 0.006, px, py, ew * 0.095)
                        pupilShade.addColorStop(0, "#050408")
                        pupilShade.addColorStop(0.58, "#090408")
                        pupilShade.addColorStop(1, "#40101a")
                        c.fillStyle = pupilShade
                        c.beginPath()
                        c.moveTo(px, py - eh * 0.20)
                        c.bezierCurveTo(px + ew * 0.075, py - eh * 0.18, px + ew * 0.075, py + eh * 0.18, px, py + eh * 0.20)
                        c.bezierCurveTo(px - ew * 0.075, py + eh * 0.18, px - ew * 0.075, py - eh * 0.18, px, py - eh * 0.20)
                        c.fill()
                    }
                    if (root.wakeTrail > 0 && root.wakeTrail < 1) {
                        var innerX = x + ew * 0.5
                        var outerX = side === 0 ? x + ew * 0.17 : x + ew * 0.83
                        var direction = side === 0 ? -1 : 1
                        var wingHeight = h * 0.23
                        for (var ripple = 0; ripple < 3; ripple++) {
                            var start = ripple * 0.17
                            var travel = (root.wakeTrail - start) / (1 - start)
                            if (travel <= 0 || travel >= 1) continue
                            var sweepX = innerX + (outerX - innerX) * travel
                            var arcHeight = wingHeight * (0.32 + travel * 0.82)
                            c.beginPath()
                            c.moveTo(sweepX, y - arcHeight * 0.22)
                            c.quadraticCurveTo(sweepX + direction * ew * (0.05 + travel * 0.13),
                                               y + arcHeight * 0.42,
                                               sweepX, y + arcHeight * 0.92)
                            c.globalAlpha = (0.94 - ripple * 0.09) * Math.pow(1 - travel, 0.72)
                            c.lineWidth = Math.max(3, h * (0.006 - travel * 0.002))
                            c.lineCap = "round"
                            c.strokeStyle = color
                            c.stroke()
                        }
                    }
                    c.restore()
                }
                c.globalAlpha = 1
                var mouthY = h * 0.79
                var talking = root.voicePlaying
                var opening = h * (talking ? 0.018 + 0.042 * (0.5 + 0.5 * Math.sin(root.glowPhase * 0.96)) : 0)
                var tilt = h * 0.040
                var left = w * 0.40, right = w * 0.60
                var lipColor = c.createLinearGradient(left, mouthY, right, mouthY)
                lipColor.addColorStop(0, "#78101e")
                lipColor.addColorStop(0.25, "#bd1c30")
                lipColor.addColorStop(0.65, "#e32a40")
                lipColor.addColorStop(1, "#921324")
                c.strokeStyle = lipColor; c.lineWidth = Math.max(3, h * 0.008)
                if (talking) {
                    c.beginPath()
                    c.moveTo(left, mouthY + tilt * 0.5)
                    c.quadraticCurveTo(w * 0.50, mouthY - opening * 0.24, right, mouthY - tilt * 0.5)
                    c.quadraticCurveTo(w * 0.58, mouthY - tilt * 0.5 + opening * 0.82, w * 0.50, mouthY + opening * 0.70)
                    c.quadraticCurveTo(w * 0.43, mouthY + tilt * 0.5 + opening * 0.45, left, mouthY + tilt * 0.5)
                    c.closePath()
                    var mouthShade = c.createLinearGradient(0, mouthY - opening * 0.4, 0, mouthY + opening * 0.8)
                    mouthShade.addColorStop(0, "#fffdfb")
                    mouthShade.addColorStop(0.7, "#f8f0f0")
                    mouthShade.addColorStop(1, "#d59ca5")
                    c.fillStyle = mouthShade; c.fill()
                    c.stroke()
                    var fangX = right - w * 0.028
                    var fangTop = mouthY - tilt * 0.36 - opening * 0.08
                    c.beginPath()
                    c.moveTo(fangX - w * 0.007, fangTop)
                    c.lineTo(fangX + w * 0.007, fangTop)
                    c.lineTo(fangX, fangTop + Math.min(opening * 0.56, h * 0.024))
                    c.closePath()
                    c.fillStyle = "#fffdf7"; c.fill()
                    c.strokeStyle = "#7b1724"; c.lineWidth = Math.max(2, h * 0.003)
                    c.stroke()
                } else {
                    c.beginPath()
                    c.moveTo(left, mouthY + tilt * 0.5)
                    c.lineTo(right, mouthY - tilt * 0.5)
                    c.stroke()
                }
            }
        }
    }

    Item {
        id: musicPanel
        visible: root.robotState === "music"
        anchors { top: parent.top; topMargin: root.height * 0.055; horizontalCenter: parent.horizontalCenter }
        width: root.width * 0.88
        height: root.height * (root.musicLyrics.length ? 0.60 : 0.68)

        Column {
            id: musicControls
            width: Math.max(66, root.width * 0.075)
            spacing: root.height * 0.018
            anchors { left: parent.left; leftMargin: parent.width * 0.09;
                verticalCenter: record.verticalCenter }
            Repeater {
                model: [
                    {glyph: "◀◀", action: "previous_music"},
                    {glyph: root.musicIsPlaying() ? "Ⅱ" : "▶",
                     action: root.musicIsPlaying() ? "pause_music" : "resume_music"},
                    {glyph: "▶▶", action: "next_music"}
                ]
                Rectangle {
                    width: musicControls.width; height: width * 0.72
                    radius: height * 0.30
                    color: controlMouse.pressed ? "#235b43" : "#123d2d"
                    border.color: "#54e5a0"; border.width: 2
                    opacity: root.musicControlPending ? 0.55 : 1
                    Text {
                        anchors.centerIn: parent
                        text: modelData.glyph; color: "#f4fff8"; font.bold: true
                        font.pixelSize: Math.max(21, parent.height * 0.43)
                    }
                    MouseArea {
                        id: controlMouse; anchors.fill: parent
                        onClicked: {
                            console.log("[DISPLAY] MUSIC_TOUCH " + modelData.action)
                            root.requestMusicControl(modelData.action)
                        }
                    }
                }
            }
        }

        Item {
            id: record
            height: Math.min(parent.height * 0.62, root.height * 0.36)
            // The Jetson framebuffer uses non-square display pixels on this HDMI panel.
            width: height * 0.76
            anchors { horizontalCenter: parent.horizontalCenter;
                horizontalCenterOffset: root.width * 0.075; top: parent.top }
            RotationAnimation on rotation {
                from: 0; to: 360; duration: 12000
                loops: Animation.Infinite; running: musicPanel.visible && root.musicIsPlaying()
            }
            Canvas {
                anchors.fill: parent
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    ctx.save()
                    ctx.translate(width / 2, height / 2)
                    ctx.scale(width / height, 1)
                    ctx.beginPath()
                    ctx.arc(0, 0, height * 0.49, 0, Math.PI * 2)
                    ctx.fillStyle = "#0c1d19"
                    ctx.fill()
                    ctx.strokeStyle = "#31d687"
                    ctx.lineWidth = Math.max(3, height * 0.012)
                    ctx.stroke()
                    for (var i = 0; i < 4; i++) {
                        ctx.beginPath()
                        ctx.arc(0, 0, height * (0.86 - i * 0.14) / 2, 0, Math.PI * 2)
                        ctx.strokeStyle = i % 2 ? "#255a43" : "#183d30"
                        ctx.lineWidth = Math.max(1, height * 0.006)
                        ctx.stroke()
                    }
                    ctx.restore()
                }
            }
            Rectangle {
                width: parent.width * 0.34; height: parent.height * 0.34; radius: width / 2
                anchors.centerIn: parent
                visible: !musicCoverCanvas.coverReady
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#76efae" }
                    GradientStop { position: 1.0; color: "#20bb77" }
                }
                Text {
                    anchors.centerIn: parent; text: "♫"; color: "#083020"; font.bold: true
                    font.pixelSize: Math.max(24, parent.width * 0.38)
                }
            }
            Canvas {
                id: musicCoverCanvas
                visible: !!root.musicCover()
                width: record.width * 0.82; height: record.height * 0.82
                anchors.centerIn: parent
                property string coverUrl: root.musicCover()
                property bool coverReady: false
                onCoverUrlChanged: {
                    coverReady = false
                    if (coverUrl) loadImage(coverUrl)
                    requestPaint()
                }
                onImageLoaded: {
                    coverReady = isImageLoaded(coverUrl)
                    requestPaint()
                }
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.clearRect(0, 0, width, height)
                    if (!coverUrl || !isImageLoaded(coverUrl)) return
                    ctx.save()
                    ctx.translate(width / 2, height / 2)
                    ctx.scale(width / height, 1)
                    ctx.beginPath()
                    ctx.arc(0, 0, height / 2, 0, Math.PI * 2)
                    ctx.closePath()
                    ctx.clip()
                    ctx.drawImage(coverUrl, -height / 2, -height / 2, height, height)
                    ctx.restore()
                }
            }
            Rectangle {
                width: parent.width * 0.06; height: parent.height * 0.06; radius: width / 2
                anchors.centerIn: parent; color: "#08241c"
            }
        }

        Row {
            id: equalizer
            width: Math.min(parent.width * 0.62, root.width * 0.56)
            height: root.height * 0.105
            spacing: width * 0.025
            anchors { horizontalCenter: parent.horizontalCenter;
                horizontalCenterOffset: root.width * 0.075;
                top: record.bottom; topMargin: root.height * 0.018 }
            Repeater {
                model: 13
                Item {
                    width: (equalizer.width - equalizer.spacing * 12) / 13
                    height: equalizer.height
                    Rectangle {
                        width: parent.width; height: parent.height * 0.28
                        anchors.bottom: parent.bottom; radius: width / 2
                        color: index % 2 ? "#78efac" : "#31d687"
                        SequentialAnimation on height {
                            running: musicPanel.visible && root.musicIsPlaying(); loops: Animation.Infinite
                            NumberAnimation { to: equalizer.height * (0.35 + (index % 5) * 0.12); duration: 240 + index * 19; easing.type: Easing.InOutQuad }
                            NumberAnimation { to: equalizer.height * (0.16 + (index % 3) * 0.08); duration: 280 + index * 13; easing.type: Easing.InOutQuad }
                        }
                    }
                }
            }
        }

    }

    Item {
        id: lowerPanel
        width: root.width * 0.92
        height: root.height * (root.robotState === "music" ?
            (root.musicLyrics.length ? 0.26 : 0.18) : 0.34)
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: root.height * 0.025 }

        Text {
            id: stateText
            visible: false
            width: parent.width; horizontalAlignment: Text.AlignHCenter
            text: root.stateLabel.toUpperCase(); color: root.accent(); font.bold: true
            font.pixelSize: Math.max(18, root.height * 0.032); font.letterSpacing: 2
        }
        Text {
            id: nowPlayingText
            visible: root.robotState === "music"
            anchors { top: parent.top }
            width: parent.width; horizontalAlignment: Text.AlignHCenter
            text: (root.musicIsPlaying() ? "正在播放：《" : "已暂停播放：《") + root.musicTitle() + "》" + (root.musicArtists() ? " · " + root.musicArtists() : "")
            color: "#d8f7e6"; font.bold: true
            font.pixelSize: Math.max(18, root.height * 0.034); elide: Text.ElideRight
        }

        Item {
            id: dialoguePanel
            visible: false
            anchors { top: stateText.bottom; topMargin: root.height * 0.010; left: parent.left; right: parent.right; bottom: parent.bottom }

            Text {
                id: userLine
                width: parent.width; horizontalAlignment: Text.AlignHCenter
                text: root.userText ? "你：" + root.userText : ""; color: "#8ba8bb"
                font.pixelSize: Math.max(15, root.height * 0.025)
                wrapMode: Text.WrapAnywhere; maximumLineCount: 2; elide: Text.ElideRight
            }
            RollingLines {
                id: assistantViewport
                anchors { top: userLine.bottom; topMargin: root.height * 0.008; left: parent.left; right: parent.right; bottom: parent.bottom }
                lines: root.assistantLines
                activeIndex: root.assistantLineIndex
                mainFontSize: Math.max(20, root.height * 0.037)
            }
        }
        RollingLines {
            id: lyricViewport
            visible: root.robotState === "music" && root.musicLyrics.length > 0
            anchors { top: nowPlayingText.bottom; topMargin: root.height * 0.008;
                left: parent.left; right: parent.right; bottom: parent.bottom }
            lines: root.musicLyrics
            activeIndex: root.musicLyricIndex
            mainFontSize: Math.max(20, root.height * 0.037)
            mainColor: "#f4fff8"
            sideColor: "#8ac5a5"
        }
    }

    Timer { id: wakeOpenDelay; interval: 260; onTriggered: root.eyeOpen = 1 }
    Timer { id: wakeHoldDone; interval: 1150; onTriggered: root.wakeHolding = false }
    NumberAnimation {
        id: wakeTrailExpand
        target: root; property: "wakeTrail"
        from: 0; to: 1; duration: 850; easing.type: Easing.Linear
    }
    Timer {
        interval: 300000
        running: root.robotState === "sleeping" && !root.eyesAsleep
        onTriggered: {
            root.eyesAsleep = true
            root.eyeOpen = 0
            root.gaze = 0
            root.gazeY = 0
        }
    }
    Timer {
        interval: 3600; repeat: true; running: root.robotState !== "music" && !root.eyesAsleep && !root.wakeHolding
        onTriggered: { root.blinking = true; closeBlink.start() }
    }
    Timer { id: closeBlink; interval: 100; onTriggered: root.blinking = false }
    Timer {
        interval: 80; repeat: true; running: root.robotState !== "music"
        onTriggered: { root.glowPhase += 1; demonFace.requestPaint() }
    }
    Timer {
        interval: 3200; repeat: true; running: root.robotState !== "music" && root.robotState !== "speaking" && !root.eyesAsleep && !root.wakeHolding
        onTriggered: {
            root.gazeStep = (root.gazeStep + 1) % 4
            var step = root.gazeStep
            root.gaze = step === 0 ? -1 : (step === 2 ? 1 : 0)
            root.gazeY = step === 1 ? -1 : (step === 3 ? 1 : 0)
        }
    }
    Timer {
        interval: root.robotState === "speaking" || root.voicePlaying ? 80 : 250
        repeat: true; running: true; triggeredOnStart: true
        onTriggered: {
            var request = new XMLHttpRequest()
            request.onreadystatechange = function() {
                if (request.readyState !== XMLHttpRequest.DONE) return
                if (request.status !== 200) { root.connected = false; return }
                try {
                    var value = JSON.parse(request.responseText)
                    root.robotState = value.state || "sleeping"
                    root.voicePlaying = value.voice_playing === true
                    root.lightInfo = value.light || root.lightInfo
                    root.stateLabel = value.label || root.robotState
                    root.userText = value.user_text || ""
                    var nextAssistantText = value.assistant_text || ""
                    var nextAssistantLines = value.assistant_lines || []
                    if (root.assistantText !== nextAssistantText ||
                            JSON.stringify(root.assistantLines) !== JSON.stringify(nextAssistantLines)) {
                        root.assistantText = nextAssistantText
                        root.assistantLines = nextAssistantLines
                    }
                    root.assistantLineIndex = value.assistant_line_index || 0
                    var nextMusic = value.music || null
                    var nextLyrics = nextMusic && nextMusic.lyrics ? nextMusic.lyrics : []
                    var nextLyricSignature = JSON.stringify(nextLyrics)
                    if (root.musicLyricSignature !== nextLyricSignature) {
                        root.musicLyricSignature = nextLyricSignature
                        root.musicLyrics = nextLyrics
                    }
                    root.musicLyricIndex = nextMusic && nextMusic.lyric_index ? nextMusic.lyric_index : 0
                    var nextMusicSignature = JSON.stringify(nextMusic)
                    if (root.musicSignature !== nextMusicSignature) {
                        root.musicSignature = nextMusicSignature
                        root.musicInfo = nextMusic
                    }
                    root.connected = true
                } catch (error) { root.connected = false }
            }
            request.open("GET", "http://127.0.0.1:8765/api/state")
            request.send()
        }
    }

    Rectangle {
        id: qqLoginButton
        z: 10
        width: Math.max(52, root.height * 0.064)
        height: width
        anchors { right: parent.right; bottom: parent.bottom; margins: Math.max(18, root.height * 0.035) }
        radius: width / 2
        color: "#190f14"
        border.color: root.qqAuthState === "ready" ? "#85313d" : "#55202c"
        border.width: 1
        Text {
            visible: false
            anchors.centerIn: parent
            text: root.qqAuthState === "ready" ?
                  "QQ 音乐 · " + (root.qqNickname || "已登录") : "QQ 音乐登录"
            color: "white"; font.bold: true
            font.pixelSize: Math.max(17, Math.min(22, root.height * 0.027))
            width: parent.width - 24; horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
        }
        Text {
            anchors.centerIn: parent
            text: "♫"
            color: "#a34c58"; font.bold: true
            font.pixelSize: parent.height * 0.63
        }
        MouseArea {
            anchors.fill: parent
            onClicked: {
                if (root.qqAuthState === "ready") root.qqAuthOpen = true
                else root.requestQqLogin()
            }
        }
    }

    Rectangle {
        id: qqLoginPanel
        z: 20
        visible: root.qqAuthOpen
        anchors.fill: parent
        color: "#ee06111d"
        Text {
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: root.height * 0.10 }
            text: root.qqAuthState === "ready" ? "QQ 音乐账号" : "QQ 音乐网页登录"
            color: "white"; font.bold: true; font.pixelSize: Math.max(28, root.height * 0.06)
        }
        Canvas {
            id: qqAvatarImage
            visible: root.qqAuthState === "ready" && root.qqHasAvatar
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: root.height * 0.23 }
            width: Math.min(210, root.height * 0.25); height: width
            property string avatarUrl: visible ? "http://127.0.0.1:8765/api/music/auth/avatar?v=" + root.qqAvatarRevision : ""
            onAvatarUrlChanged: {
                if (avatarUrl) loadImage(avatarUrl)
                requestPaint()
            }
            onImageLoaded: requestPaint()
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                if (!avatarUrl || !isImageLoaded(avatarUrl)) return
                ctx.save()
                ctx.beginPath()
                ctx.arc(width / 2, height / 2, width / 2, 0, Math.PI * 2)
                ctx.closePath()
                ctx.clip()
                ctx.drawImage(avatarUrl, 0, 0, width, height)
                ctx.restore()
            }
        }
        Item {
            id: qqBrowserPane
            visible: root.qqAuthState === "browser"
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: root.height * 0.16 }
            width: root.width * 0.96
            height: root.height * 0.68
            Image {
                id: qqBrowserImageA
                anchors.fill: parent
                visible: root.qqBrowserSlot === 0
                fillMode: Image.PreserveAspectFit
                smooth: false; cache: false; asynchronous: true
                onStatusChanged: {
                    if (status === Image.Ready && root.qqAuthState === "browser") root.qqBrowserSlot = 0
                }
            }
            Image {
                id: qqBrowserImageB
                anchors.fill: parent
                visible: root.qqBrowserSlot === 1
                fillMode: Image.PreserveAspectFit
                smooth: false; cache: false; asynchronous: true
                onStatusChanged: {
                    if (status === Image.Ready && root.qqAuthState === "browser") root.qqBrowserSlot = 1
                }
            }
            MouseArea {
                anchors.fill: parent
                onClicked: {
                    var active = root.qqBrowserSlot === 0 ? qqBrowserImageA : qqBrowserImageB
                    if (active.paintedWidth <= 0 || active.paintedHeight <= 0) return
                    var left = (parent.width - active.paintedWidth) / 2
                    var top = (parent.height - active.paintedHeight) / 2
                    var x = (mouse.x - left) / active.paintedWidth
                    var y = (mouse.y - top) / active.paintedHeight
                    if (x >= 0 && x <= 1 && y >= 0 && y <= 1) root.clickQqBrowser(x, y)
                }
            }
        }
        Rectangle {
            visible: root.qqAuthState === "browser" && root.qqQrAvailable
            anchors { left: parent.left; leftMargin: root.width * 0.02; verticalCenter: parent.verticalCenter }
            width: Math.min(240, root.width * 0.21)
            height: width + 42
            radius: 10; color: "white"; border.color: "#41ca9a"; border.width: 2
            Image {
                anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 12 }
                width: parent.width - 24; height: width
                fillMode: Image.PreserveAspectFit; smooth: false; cache: false
                source: parent.visible ? "http://127.0.0.1:8765/api/music/auth/qr?v=" + root.qqQrToken : ""
            }
            Text {
                anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 8 }
                text: "手机 QQ 扫码"; color: "#15232e"; font.pixelSize: 19
            }
        }
        Text {
            visible: root.qqAuthState !== "browser"
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: root.height * 0.67 }
            width: parent.width * 0.82; horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            text: root.qqAuthState === "qr" ? "请使用手机 QQ 扫码并确认登录" :
                  root.qqAuthState === "ready" ? "已登录：" + (root.qqNickname || "QQ 用户") :
                  root.qqAuthState === "required" ? "尚未登录 QQ 音乐" :
                  root.qqAuthDetail || "正在打开登录二维码…"
            color: "#effcff"; font.pixelSize: Math.max(20, root.height * 0.037)
        }
        Row {
            anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: root.height * 0.08 }
            spacing: 16
            Repeater {
                model: root.qqAuthState === "ready" ? ["退出登录", "切换用户", "关闭"] : ["关闭"]
                Rectangle {
                    width: 154; height: 52; radius: 12; color: "#24465c"
                    Text { anchors.centerIn: parent; text: modelData; color: "white"; font.pixelSize: 21 }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            if (modelData === "退出登录") root.requestQqLogout(false)
                            else if (modelData === "切换用户") root.requestQqLogout(true)
                            else root.closeQqPanel()
                        }
                    }
                }
            }
        }
    }

    Timer {
        id: closeAuthPanel
        interval: 4000
        onTriggered: { if (root.qqAuthState === "ready") root.qqAuthOpen = false }
    }

    Timer {
        interval: 1300; repeat: true; running: root.qqAuthState === "browser"; triggeredOnStart: true
        onTriggered: {
            var target = root.qqBrowserSlot === 0 ? qqBrowserImageB : qqBrowserImageA
            if (target.status === Image.Loading) return
            root.qqBrowserRevision += 1
            var url = "http://127.0.0.1:8765/api/music/auth/browser?v=" + root.qqBrowserRevision
            target.source = url
        }
    }

    Timer {
        interval: 2000; repeat: true; running: true; triggeredOnStart: true
        onTriggered: {
            var request = new XMLHttpRequest()
            request.onreadystatechange = function() {
                if (request.readyState !== XMLHttpRequest.DONE || request.status !== 200) return
                try {
                    var auth = JSON.parse(request.responseText)
                    if (root.qqAuthState !== auth.state && (auth.state === "qr" || auth.state === "browser")) {
                        root.qqQrRevision += 1
                        root.qqAuthOpen = true
                        qqBrowserImageA.source = ""
                        qqBrowserImageB.source = ""
                        root.qqBrowserSlot = 0
                    }
                    if (root.qqAuthState !== auth.state && auth.state === "ready") closeAuthPanel.start()
                    if (root.qqAuthState !== auth.state && auth.state === "ready") root.qqAvatarRevision += 1
                    root.qqAuthState = auth.state || "unknown"
                    root.qqAuthDetail = auth.detail || ""
                    root.qqNickname = auth.nickname || ""
                    root.qqHasAvatar = !!auth.avatar
                    root.qqQrAvailable = !!auth.qr_available
                    root.qqQrToken = auth.qr_revision || 0
                    if (root.qqSwitchPending && root.qqAuthState === "required") {
                        root.qqSwitchPending = false
                        root.requestQqLogin()
                    }
                } catch (error) { }
            }
            request.open("GET", "http://127.0.0.1:8765/api/music/auth")
            request.send()
        }
    }
}
