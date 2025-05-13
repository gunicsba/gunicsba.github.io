/****************************************************************************
** Meta object code from reading C++ file 'widget.h'
**
** Created by: The Qt Meta Object Compiler version 67 (Qt 5.14.2)
**
** WARNING! All changes made in this file will be lost!
*****************************************************************************/

#include <memory>
#include "../../KEY_PRO/widget.h"
#include <QtCore/qbytearray.h>
#include <QtCore/qmetatype.h>
#if !defined(Q_MOC_OUTPUT_REVISION)
#error "The header file 'widget.h' doesn't include <QObject>."
#elif Q_MOC_OUTPUT_REVISION != 67
#error "This file was generated using the moc from 5.14.2. It"
#error "cannot be used with the include files from this version of Qt."
#error "(The moc has changed too much.)"
#endif

QT_BEGIN_MOC_NAMESPACE
QT_WARNING_PUSH
QT_WARNING_DISABLE_DEPRECATED
struct qt_meta_stringdata_Widget_t {
    QByteArrayData data[20];
    char stringdata0[339];
};
#define QT_MOC_LITERAL(idx, ofs, len) \
    Q_STATIC_BYTE_ARRAY_DATA_HEADER_INITIALIZER_WITH_OFFSET(len, \
    qptrdiff(offsetof(qt_meta_stringdata_Widget_t, stringdata0) + ofs \
        - idx * sizeof(QByteArrayData)) \
    )
static const qt_meta_stringdata_Widget_t qt_meta_stringdata_Widget = {
    {
QT_MOC_LITERAL(0, 0, 6), // "Widget"
QT_MOC_LITERAL(1, 7, 24), // "on_confirmButton_clicked"
QT_MOC_LITERAL(2, 32, 0), // ""
QT_MOC_LITERAL(3, 33, 22), // "on_CleanButton_clicked"
QT_MOC_LITERAL(4, 56, 25), // "on_CleanALLButton_clicked"
QT_MOC_LITERAL(5, 82, 26), // "Read_configuration_clicked"
QT_MOC_LITERAL(6, 109, 16), // "on_clean_DevData"
QT_MOC_LITERAL(7, 126, 9), // "SendLayer"
QT_MOC_LITERAL(8, 136, 5), // "index"
QT_MOC_LITERAL(9, 142, 11), // "timeoutSlot"
QT_MOC_LITERAL(10, 154, 20), // "on_changeButtonGroup"
QT_MOC_LITERAL(11, 175, 2), // "id"
QT_MOC_LITERAL(12, 178, 21), // "Set_Keyboard_Ver_SLOT"
QT_MOC_LITERAL(13, 200, 27), // "on_tabWidget_currentChanged"
QT_MOC_LITERAL(14, 228, 19), // "on_download_clicked"
QT_MOC_LITERAL(15, 248, 18), // "slotSpinbox_slider"
QT_MOC_LITERAL(16, 267, 18), // "slotslider_Spinbox"
QT_MOC_LITERAL(17, 286, 15), // "onTimeupDestroy"
QT_MOC_LITERAL(18, 302, 17), // "on_change_clicked"
QT_MOC_LITERAL(19, 320, 18) // "KB_UpData_SoftWare"

    },
    "Widget\0on_confirmButton_clicked\0\0"
    "on_CleanButton_clicked\0on_CleanALLButton_clicked\0"
    "Read_configuration_clicked\0on_clean_DevData\0"
    "SendLayer\0index\0timeoutSlot\0"
    "on_changeButtonGroup\0id\0Set_Keyboard_Ver_SLOT\0"
    "on_tabWidget_currentChanged\0"
    "on_download_clicked\0slotSpinbox_slider\0"
    "slotslider_Spinbox\0onTimeupDestroy\0"
    "on_change_clicked\0KB_UpData_SoftWare"
};
#undef QT_MOC_LITERAL

static const uint qt_meta_data_Widget[] = {

 // content:
       8,       // revision
       0,       // classname
       0,    0, // classinfo
      16,   14, // methods
       0,    0, // properties
       0,    0, // enums/sets
       0,    0, // constructors
       0,       // flags
       0,       // signalCount

 // slots: name, argc, parameters, tag, flags
       1,    0,   94,    2, 0x0a /* Public */,
       3,    0,   95,    2, 0x0a /* Public */,
       4,    0,   96,    2, 0x0a /* Public */,
       5,    0,   97,    2, 0x0a /* Public */,
       6,    0,   98,    2, 0x0a /* Public */,
       7,    1,   99,    2, 0x0a /* Public */,
       9,    0,  102,    2, 0x0a /* Public */,
      10,    1,  103,    2, 0x0a /* Public */,
      12,    1,  106,    2, 0x0a /* Public */,
      13,    1,  109,    2, 0x08 /* Private */,
      14,    0,  112,    2, 0x08 /* Private */,
      15,    0,  113,    2, 0x08 /* Private */,
      16,    0,  114,    2, 0x08 /* Private */,
      17,    0,  115,    2, 0x08 /* Private */,
      18,    0,  116,    2, 0x08 /* Private */,
      19,    0,  117,    2, 0x08 /* Private */,

 // slots: parameters
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void, QMetaType::Int,    8,
    QMetaType::Void,
    QMetaType::Void, QMetaType::Int,   11,
    QMetaType::Void, QMetaType::Int,   11,
    QMetaType::Void, QMetaType::Int,    8,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,
    QMetaType::Void,

       0        // eod
};

void Widget::qt_static_metacall(QObject *_o, QMetaObject::Call _c, int _id, void **_a)
{
    if (_c == QMetaObject::InvokeMetaMethod) {
        auto *_t = static_cast<Widget *>(_o);
        Q_UNUSED(_t)
        switch (_id) {
        case 0: _t->on_confirmButton_clicked(); break;
        case 1: _t->on_CleanButton_clicked(); break;
        case 2: _t->on_CleanALLButton_clicked(); break;
        case 3: _t->Read_configuration_clicked(); break;
        case 4: _t->on_clean_DevData(); break;
        case 5: _t->SendLayer((*reinterpret_cast< int(*)>(_a[1]))); break;
        case 6: _t->timeoutSlot(); break;
        case 7: _t->on_changeButtonGroup((*reinterpret_cast< int(*)>(_a[1]))); break;
        case 8: _t->Set_Keyboard_Ver_SLOT((*reinterpret_cast< int(*)>(_a[1]))); break;
        case 9: _t->on_tabWidget_currentChanged((*reinterpret_cast< int(*)>(_a[1]))); break;
        case 10: _t->on_download_clicked(); break;
        case 11: _t->slotSpinbox_slider(); break;
        case 12: _t->slotslider_Spinbox(); break;
        case 13: _t->onTimeupDestroy(); break;
        case 14: _t->on_change_clicked(); break;
        case 15: _t->KB_UpData_SoftWare(); break;
        default: ;
        }
    }
}

QT_INIT_METAOBJECT const QMetaObject Widget::staticMetaObject = { {
    QMetaObject::SuperData::link<QWidget::staticMetaObject>(),
    qt_meta_stringdata_Widget.data,
    qt_meta_data_Widget,
    qt_static_metacall,
    nullptr,
    nullptr
} };


const QMetaObject *Widget::metaObject() const
{
    return QObject::d_ptr->metaObject ? QObject::d_ptr->dynamicMetaObject() : &staticMetaObject;
}

void *Widget::qt_metacast(const char *_clname)
{
    if (!_clname) return nullptr;
    if (!strcmp(_clname, qt_meta_stringdata_Widget.stringdata0))
        return static_cast<void*>(this);
    if (!strcmp(_clname, "HID_Key_Val"))
        return static_cast< HID_Key_Val*>(this);
    return QWidget::qt_metacast(_clname);
}

int Widget::qt_metacall(QMetaObject::Call _c, int _id, void **_a)
{
    _id = QWidget::qt_metacall(_c, _id, _a);
    if (_id < 0)
        return _id;
    if (_c == QMetaObject::InvokeMetaMethod) {
        if (_id < 16)
            qt_static_metacall(this, _c, _id, _a);
        _id -= 16;
    } else if (_c == QMetaObject::RegisterMethodArgumentMetaType) {
        if (_id < 16)
            *reinterpret_cast<int*>(_a[0]) = -1;
        _id -= 16;
    }
    return _id;
}
QT_WARNING_POP
QT_END_MOC_NAMESPACE
