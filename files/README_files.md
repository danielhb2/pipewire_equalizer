## Ubicación de los archivos

Para que la GUI pueda mostrar el archivo README desde su botón de lectura integrado, es necesario que los archivos de documentación (`README.md` o `README.en.md`) se encuentren en el **mismo directorio** donde se ejecuta el script `eq_gui.py`.

```
eq.conf           → ~/.config/pipewire/pipewire.conf.d/eq.conf
compressor.conf   → ~/.config/pipewire/pipewire.conf.d/compressor.conf
eq_gui.py         → en cualquier ubicación, se ejecuta con python3
README.md  → en el mismo directorio del script (para accederlo desde la GUI)
README.en.md (opcional, en el mismo directorio del script)
