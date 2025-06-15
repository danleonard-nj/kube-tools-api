import sys
import base64
from PyQt5.QtWidgets import QApplication, QWidget, QTextEdit, QVBoxLayout
from PyQt5.QtGui import QImage, QClipboard
from PyQt5.QtCore import QBuffer, QByteArray, QEvent


class ImagePasteTextEdit(QTextEdit):
    def insertFromMimeData(self, source):
        try:
            if source.hasImage():
                image = source.imageData()
                buffer = QBuffer()
                buffer.open(QBuffer.WriteOnly)
                image.save(buffer, "PNG")
                base64_data = base64.b64encode(buffer.data()).decode()
                self.setPlainText(base64_data)
                # Automatically copy to clipboard
                clipboard = QApplication.clipboard()
                clipboard.setText(base64_data)
            else:
                super().insertFromMimeData(source)
        except Exception as e:
            print(f"Exception in insertFromMimeData: {e}")
            self.setPlainText(f"Error: {e}")


class ImageToBase64App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image to Base64")
        self.resize(600, 400)

        self.textbox = ImagePasteTextEdit()
        self.textbox.setPlaceholderText("Paste an image (Ctrl+V) here...")

        layout = QVBoxLayout()
        layout.addWidget(self.textbox)
        self.setLayout(layout)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ImageToBase64App()
    window.show()
    sys.exit(app.exec_())
