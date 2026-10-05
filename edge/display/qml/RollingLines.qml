import QtQuick 2.12

Flickable {
    id: roller
    property var lines: []
    property int activeIndex: 0
    property int mainFontSize: 28
    property color mainColor: "#effcff"
    property color sideColor: "#83a3b7"
    property real rowHeight: height / 3
    contentWidth: width
    contentHeight: lineColumn.height
    contentY: Math.max(0, Math.min(activeIndex, Math.max(0, lines.length - 1))) * rowHeight
    clip: true
    interactive: false
    boundsBehavior: Flickable.StopAtBounds
    Behavior on contentY { NumberAnimation { duration: 280; easing.type: Easing.InOutQuad } }

    Column {
        id: lineColumn
        width: roller.width
        Item { width: parent.width; height: roller.rowHeight }
        Repeater {
            model: roller.lines || []
            Text {
                width: lineColumn.width
                height: roller.rowHeight
                text: modelData
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                maximumLineCount: 2
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: index === roller.activeIndex ? roller.mainColor : roller.sideColor
                opacity: Math.abs(index - roller.activeIndex) <= 1 ? 1 : 0.3
                font.bold: index === roller.activeIndex
                font.pixelSize: index === roller.activeIndex ? roller.mainFontSize :
                    Math.max(20, Math.round(roller.mainFontSize * 0.86))
            }
        }
        Item { width: parent.width; height: roller.rowHeight }
    }
}
