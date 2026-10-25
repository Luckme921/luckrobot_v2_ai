import QtQuick 2.12
Item {
    id: field
    property string label: ""
    property alias text: input.text
    property bool secret: false
    signal editing(var editor)
    height: 66
    Text { text: field.label; color: "#a5c4ca"; font.pixelSize: 16 }
    Rectangle {
        y: 23; width: parent.width; height: 40; radius: 7
        color: "#122730"; border.color: input.activeFocus ? "#55dfbe" : "#42606a"
        TextInput {
            id: input; anchors.fill: parent; anchors.margins: 8
            color: "#ffffff"; font.pixelSize: 20; clip: true
            echoMode: field.secret ? TextInput.Password : TextInput.Normal
            maximumLength: 128; selectByMouse: true
            onActiveFocusChanged: if (activeFocus) field.editing(input)
            MouseArea {
                anchors.fill: parent
                onPressed: { input.forceActiveFocus(); field.editing(input); mouse.accepted = false }
            }
        }
    }
}
