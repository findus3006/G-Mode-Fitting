@echo off
rem Start the G-mode fit GUI (double-click, or drop a spectrum file onto this .bat).
rem Needs numpy, scipy, matplotlib, PySide6 and the kpfm_pl toolbox. If kpfm_pl is
rem not installed, its source next to this repository (..\kpfm_pl\src) is used.
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0..\kpfm_pl\src;%PYTHONPATH%"

python -c "import gmode_fit.gui" || (
    echo.
    echo The G-mode fit GUI could not be started; see the error above.
    echo Install the kpfm_pl toolbox with its GUI extra in its folder:
    echo     pip install -e .[gui]
    echo.
    pause
    exit /b 1
)

rem pythonw starts the window without keeping a console open.
start "" pythonw -m gmode_fit %1
