@echo off
rem Timonel - Windows: double-click to start / doble clic para arrancar
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw timonel.py %* & exit /b)
where pythonw >nul 2>nul && (start "" pythonw timonel.py %* & exit /b)
where py >nul 2>nul && (start "" py timonel.py %* & exit /b)
where python >nul 2>nul && (start "" python timonel.py %* & exit /b)
echo.
echo  Python 3 is not installed.  /  Python 3 no esta instalado.
echo  https://www.python.org/downloads/   (or / o: winget install Python.Python.3.12)
echo.
pause
