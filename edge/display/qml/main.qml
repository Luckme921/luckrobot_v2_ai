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
    property var assistantLines: []
    property int assistantLineIndex: 0
    property var musicInfo: null
    property string musicSignature: ""
    property bool blinking: false
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
            GradientStop { position: 0.0; color: root.robotState === "music" ? "#27133d" : "#102b3b" }
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
        anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 20 }
        text: "状态连接中…"; color: "#ffb5b5"; opacity: root.connected ? 0 : 1
        font.pixelSize: Math.max(16, root.height * 0.025)
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }

    Rectangle {
        id: face
        visible: root.robotState !== "music"
        width: Math.min(root.width * 0.62, root.height * 0.70)
        height: width / 1.45
        anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: root.height * 0.065 }
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
            width: face.width * 0.19
            height: speakingAnimation.running ? face.height * 0.11 : face.height * 0.025
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: face.height * 0.68 }
            radius: height / 2; color: "transparent"
            border.width: Math.max(3, face.height * 0.018); border.color: root.accent()
            SequentialAnimation on scale {
                id: speakingAnimation
                running: root.robotState === "speaking"
                loops: Animation.Infinite
                NumberAnimation { to: 0.62; duration: 130 }
                NumberAnimation { to: 1.18; duration: 130 }
            }
        }
    }

    Item {
        id: musicPanel
        visible: root.robotState === "music"
        anchors { top: parent.top; topMargin: root.height * 0.055; horizontalCenter: parent.horizontalCenter }
        width: root.width * 0.88
        height: root.height * (root.musicInfo && root.musicInfo.lyrics ? 0.60 : 0.68)

        Item {
            id: record
            width: Math.min(parent.width * 0.42, parent.height * 0.62)
            height: width
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top }
            RotationAnimation on rotation {
                from: 0; to: 360; duration: 12000
                loops: Animation.Infinite; running: musicPanel.visible
            }
            Rectangle {
                anchors.fill: parent; radius: width / 2
                color: "#11131a"; border.color: "#b98cff"; border.width: Math.max(3, width * 0.012)
            }
            Repeater {
                model: 4
                Rectangle {
                    width: record.width * (0.86 - index * 0.14)
                    height: width; radius: width / 2
                    anchors.centerIn: parent; color: "transparent"
                    border.color: index % 2 ? "#433451" : "#2c2732"
                    border.width: Math.max(1, record.width * 0.006)
                }
            }
            Rectangle {
                width: parent.width * 0.34; height: width; radius: width / 2
                anchors.centerIn: parent
                visible: !musicCoverCanvas.coverReady
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#66e6ff" }
                    GradientStop { position: 1.0; color: "#b98cff" }
                }
                Text {
                    anchors.centerIn: parent; text: "♫"; color: "#07111d"; font.bold: true
                    font.pixelSize: Math.max(24, parent.width * 0.38)
                }
            }
            Canvas {
                id: musicCoverCanvas
                visible: !!root.musicCover()
                width: record.width * 0.82; height: width
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
                    ctx.beginPath()
                    ctx.arc(width / 2, height / 2, width / 2, 0, Math.PI * 2)
                    ctx.closePath()
                    ctx.clip()
                    ctx.drawImage(coverUrl, 0, 0, width, height)
                    ctx.restore()
                }
            }
            Rectangle {
                width: parent.width * 0.06; height: width; radius: width / 2
                anchors.centerIn: parent; color: "#07111d"
            }
        }

        Row {
            id: equalizer
            width: Math.min(parent.width * 0.62, root.width * 0.56)
            height: root.height * 0.105
            spacing: width * 0.025
            anchors { horizontalCenter: parent.horizontalCenter; top: record.bottom; topMargin: root.height * 0.018 }
            Repeater {
                model: 13
                Item {
                    width: (equalizer.width - equalizer.spacing * 12) / 13
                    height: equalizer.height
                    Rectangle {
                        width: parent.width; height: parent.height * 0.28
                        anchors.bottom: parent.bottom; radius: width / 2
                        color: index % 2 ? "#66e6ff" : "#b98cff"
                        SequentialAnimation on height {
                            running: musicPanel.visible; loops: Animation.Infinite
                            NumberAnimation { to: equalizer.height * (0.35 + (index % 5) * 0.12); duration: 240 + index * 19; easing.type: Easing.InOutQuad }
                            NumberAnimation { to: equalizer.height * (0.16 + (index % 3) * 0.08); duration: 280 + index * 13; easing.type: Easing.InOutQuad }
                        }
                    }
                }
            }
        }

        Text {
            id: musicTitleText
            anchors { top: equalizer.bottom; topMargin: root.height * 0.018; horizontalCenter: parent.horizontalCenter }
            width: parent.width * 0.92; horizontalAlignment: Text.AlignHCenter
            text: root.musicTitle(); color: "#f7f1ff"; font.bold: true
            font.pixelSize: Math.max(24, root.height * 0.052)
            elide: Text.ElideRight
        }
        Text {
            anchors { top: musicTitleText.bottom; topMargin: root.height * 0.008; horizontalCenter: parent.horizontalCenter }
            width: parent.width * 0.88; horizontalAlignment: Text.AlignHCenter
            text: root.musicArtists(); color: "#b9d6e5"
            font.pixelSize: Math.max(17, root.height * 0.030)
            elide: Text.ElideRight
        }
    }

    Item {
        id: lowerPanel
        width: root.width * 0.92
        height: root.height * (root.robotState === "music" ?
            (root.musicInfo && root.musicInfo.lyrics ? 0.26 : 0.18) : 0.34)
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: root.height * 0.025 }

        Text {
            id: stateText
            visible: root.robotState !== "music"
            width: parent.width; horizontalAlignment: Text.AlignHCenter
            text: root.stateLabel.toUpperCase(); color: root.accent(); font.bold: true
            font.pixelSize: Math.max(18, root.height * 0.032); font.letterSpacing: 2
        }
        Text {
            id: nowPlayingText
            visible: root.robotState === "music"
            anchors { top: parent.top }
            width: parent.width; horizontalAlignment: Text.AlignHCenter
            text: "正在播放：《" + root.musicTitle() + "》" + (root.musicArtists() ? " · " + root.musicArtists() : "")
            color: "#effcff"; font.bold: true
            font.pixelSize: Math.max(18, root.height * 0.034); elide: Text.ElideRight
        }

        Item {
            id: dialoguePanel
            visible: root.robotState !== "music"
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
            visible: root.robotState === "music" && !!(root.musicInfo && root.musicInfo.lyrics)
            anchors { top: nowPlayingText.bottom; topMargin: root.height * 0.008;
                left: parent.left; right: parent.right; bottom: parent.bottom }
            lines: root.musicInfo && root.musicInfo.lyrics ? root.musicInfo.lyrics : []
            activeIndex: root.musicInfo && root.musicInfo.lyric_index ? root.musicInfo.lyric_index : 0
            mainFontSize: Math.max(20, root.height * 0.037)
            mainColor: "#f7f1ff"
            sideColor: "#9c86b7"
        }
    }

    Timer {
        interval: 5200; repeat: true; running: root.robotState !== "sleeping" && root.robotState !== "music"
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
                    var nextAssistantText = value.assistant_text || ""
                    if (root.assistantText !== nextAssistantText) {
                        root.assistantText = nextAssistantText
                        root.assistantLines = value.assistant_lines || []
                    }
                    root.assistantLineIndex = value.assistant_line_index || 0
                    var nextMusic = value.music || null
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
        width: Math.max(230, root.width * 0.18)
        height: Math.max(45, root.height * 0.07)
        anchors { left: parent.left; top: parent.top; margins: 20 }
        radius: 12
        color: root.qqAuthState === "required" ? "#9b3f52" : "#173849"
        border.color: root.qqAuthState === "ready" ? "#52ffd2" : "#66e6ff"
        Text {
            anchors.centerIn: parent
            text: root.qqAuthState === "ready" ?
                  "QQ 音乐 · " + (root.qqNickname || "已登录") : "QQ 音乐登录"
            color: "white"; font.bold: true
            font.pixelSize: Math.max(17, Math.min(22, root.height * 0.027))
            width: parent.width - 24; horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
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
