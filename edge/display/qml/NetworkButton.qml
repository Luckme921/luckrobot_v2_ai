import QtQuick 2.12
Rectangle {
    id: button
    property string text: ""
    property bool selected: false
    signal clicked()
    implicitWidth: 140
    implicitHeight: 46
    radius: 9
    color: !enabled ? "#26333c" : (selected ? "#176f67" : "#193844")
    border.color: selected ? "#58ebcd" : "#3c6775"
    Text { anchors.centerIn: parent; text: button.text; color: button.enabled ? "#ecfffa" : "#80949e"; font.pixelSize: 18 }
    MouseArea { anchors.fill: parent; enabled: button.enabled; onClicked: button.clicked() }
}
