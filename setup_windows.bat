@echo off
echo =============================================
echo  White Stork Migration Visualiser - Setup
echo =============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.11 from https://www.python.org/downloads/
    echo Make sure to tick "Add Python to PATH" during install.
    pause
    exit /b 1
)
echo [OK] Python found

:: Install Python packages
echo.
echo Installing Python packages (this may take a few minutes)...
pip install flask flask-login flask-sqlalchemy flask-bcrypt pandas geopandas movingpandas openpyxl shapely scipy pyproj pymysql cryptography
if errorlevel 1 (
    echo ERROR: Failed to install packages.
    pause
    exit /b 1
)
echo [OK] Packages installed

:: Setup MySQL database
echo.
echo Setting up database...
echo Please enter your MySQL root password when prompted:
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS stork_db; CREATE USER IF NOT EXISTS 'stork_user'@'localhost' IDENTIFIED BY 'stork_pass2024'; GRANT ALL PRIVILEGES ON stork_db.* TO 'stork_user'@'localhost'; FLUSH PRIVILEGES;"
if errorlevel 1 (
    echo ERROR: MySQL setup failed. Make sure MySQL is installed and running.
    pause
    exit /b 1
)
echo [OK] Database and user created

echo Importing data...
mysql -u root -p stork_db < stork_db.sql
if errorlevel 1 (
    echo ERROR: Data import failed.
    pause
    exit /b 1
)
echo [OK] Data imported

echo.
echo =============================================
echo  Setup complete! Starting the application...
echo  Open your browser at: http://localhost:5000
echo =============================================
echo.
echo Login credentials:
echo   Admin   - username: admin    password: admin123
echo   User    - username: fenil    password: fenil123
echo.
python backend/app.py
pause
