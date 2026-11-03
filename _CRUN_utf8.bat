@ECHO OFF
@CHCP 866
:: if "%~1" == "" (start "" /min "%comspec%" /c "%~f0" any_word & exit /b)
CD /d "%~dp0."
SET xosx=
IF %PROCESSOR_ARCHITECTURE% == x86 (IF NOT DEFINED PROCESSOR_ARCHITEW6432 GOTO bit32)
GOTO bit64
:bit32
SET xos=x32
SET xosx=
GOTO start
:bit64
SET xos=x64
SET xosx=-x64

:start

SET AUTHOR=A1eksandr1
SET COMPANY=FORUM.RU-BOARD.COM
SET WINDOWCOLS=80
SET WINDOWLINES=50
SET MENU1=0
SET STRT1=START /WAIT ""
SET STRT1=1>nul 2>&1
SET STRT2=START ""
SET CONS=NULL
SET ZM=ОТСУТСТВ
SET RES=ОТСУТСТВУЕТ!
SET RESP=НЕОПРЕДЕЛЕН!!!
SET RESIP=!!НЕОПРЕДЕЛЕН!!
SET RESONL=ОТСУТСТВ
SET RESRLN=ОТСУТСТВ
SET LDR=НЕОПРЕДЕЛЕН!
SET REGFLAG=0
SET REGTEST=1
SET SYS=000

IF EXIST CONS.EXE             FOR /f "tokens=*" %%i in ('dir /b CONS.EXE')            do SET ZM=%%i
IF EXIST VR4*.res             FOR /f "tokens=*" %%i in ('dir /b VR4*.res')            do SET RES=%%i
IF EXIST HT4*.res             FOR /f "tokens=*" %%i in ('dir /b HT4*.res')            do SET RES=%%i
IF EXIST SH4*.res             FOR /f "tokens=*" %%i in ('dir /b SH4*.res')            do SET RES=%%i
IF EXIST VR4*.exe             FOR /f "tokens=*" %%i in ('dir /b VR4*.exe')            do SET RESP=%%i
IF EXIST HT4*.exe             FOR /f "tokens=*" %%i in ('dir /b HT4*.exe')            do SET RESP=%%i
IF EXIST SH4*.exe             FOR /f "tokens=*" %%i in ('dir /b SH4*.exe')            do SET RESP=%%i
IF EXIST VR4*.res.p           FOR /f "tokens=*" %%i in ('dir /b VR4*.res.p')          do SET RESP=%%i
IF EXIST HT4*.res.p           FOR /f "tokens=*" %%i in ('dir /b HT4*.res.p')          do SET RESP=%%i
IF EXIST SH4*.res.p           FOR /f "tokens=*" %%i in ('dir /b SH4*.res.p')          do SET RESP=%%i
IF EXIST VR4*.res.ip          FOR /f "tokens=*" %%i in ('dir /b VR4*.res.ip')         do SET RESIP=%%i
IF EXIST HT4*.res.ip          FOR /f "tokens=*" %%i in ('dir /b HT4*.res.ip')         do SET RESIP=%%i
IF EXIST SH4*.res.ip          FOR /f "tokens=*" %%i in ('dir /b SH4*.res.ip')         do SET RESIP=%%i
IF EXIST VR4*.res.ONL         FOR /f "tokens=*" %%i in ('dir /b VR4*.res.ONL')        do SET RESONL=%%i
IF EXIST HT4*.res.ONL         FOR /f "tokens=*" %%i in ('dir /b HT4*.res.ONL')        do SET RESONL=%%i
IF EXIST SH4*.res.ONL         FOR /f "tokens=*" %%i in ('dir /b SH4*.res.ONL')        do SET RESONL=%%i
IF EXIST VR4*.res.RLN         FOR /f "tokens=*" %%i in ('dir /b VR4*.res.RLN')        do SET RESRLN=%%i
IF EXIST HT4*.res.RLN         FOR /f "tokens=*" %%i in ('dir /b HT4*.res.RLN')        do SET RESRLN=%%i
IF EXIST SH4*.res.RLN         FOR /f "tokens=*" %%i in ('dir /b SH4*.res.RLN')        do SET RESRLN=%%i
IF EXIST _*_*.exe             FOR /f "tokens=*" %%i in ('dir /b _*_*.exe')            do SET LDR=%%i
    IF EXIST SYSTEM\f*.cpr       SET SYS=RUS
    IF EXIST SYSTEM\g*.cpr       SET SYS=RUS
    IF EXIST SYSTEM\bel_qs*.cfg  SET SYS=BEL
    IF EXIST SYSTEM\bel_sl*.cfg  SET SYS=BEL
REM IF EXIST SYSTEM\bel_sp*.cfg  SET SYS=BEL
    IF EXIST SYSTEM\bel_st*.cfg  SET SYS=BEL
REM IF EXIST SYSTEM\uni_bel.cfg  SET SYS=BEL

CALL :DATTIM
CALL :WEEK
TITLE ConsPlus Evol by %author% -= %TIM% / %DAT% / %DayOfWeek% / %mmm% =-
MODE CON COLS=%WINDOWCOLS% LINES=%WINDOWLINES%
COLOR 1A

REM ##################################################################################################################################################
REM Используем ТМ с оригинальным именем, если не нашли патченного, устанавливаем единое значение для обоих
IF "%RESP%"=="НЕОПРЕДЕЛЕН!!!" SET RESP=%RES%
REM Используем найденный патченный ТМ, с учётом возможного переназначения выше
IF "%CONS%"=="NULL" SET CONS=%RESP%
REM Пробуем использовать загрузчик, если не нашли иного
IF "%CONS%"=="ОТСУТСТВУЕТ!" SET CONS=%ZM%
REM Не нашли ничего...
IF "%CONS%"=="ОТСУТСТВ" (
   ECHO Программные файлы К+ не найдены.
   ECHO Работа невозможна.
   PAUSE
   EXIT
   )
REM Принудительно используем загрузчик, т.е. запускаемый модуль cons.exe, если тип комплекта VR (пользователь)
IF /I "%RES:~0,-10%"=="VR" SET CONS=%ZM%
REM ##################################################################################################################################################
CLS
ECHO ПРОВЕРКА И СОЗДАНИЕ ОТСУТСТВУЮЩИХ СТРУКТУР...
ECHO ОЖИДАЙТЕ...
IF EXIST ADM\NULL DEL /q /s /f NULL   >nul 2>&1
IF EXIST DISTR\BIS\NULL DEL /q /s /f NULL   >nul 2>&1
IF NOT EXIST ADM MD ADM
IF NOT EXIST BASE MD BASE
IF NOT EXIST DISTR\BIS MD DISTR\BIS
IF NOT EXIST DISTR\DIN MD DISTR\DIN
IF NOT EXIST RECEIVE MD RECEIVE
IF NOT EXIST SEND MD SEND
IF NOT EXIST SYSTEM MD SYSTEM
::first_run
IF NOT EXIST ADM\A1R1 ATTRIB -R -A -S -H *.* /S /D   >nul 2>&1
IF NOT EXIST ADM\A1R1 <nul set /p x=>ADM\A1R1
IF NOT EXIST ADM\A1R1 copy nul ADM\A1R1
::next_run
ATTRIB "ADM"|>Nul FindStr /BIR ".....R"&& ATTRIB -R -A -S -H *.* /S /D
ATTRIB "BASE"|>Nul FindStr /BIR ".....R"&& ATTRIB -R -A -S -H *.* /S /D
ATTRIB "DISTR"|>Nul FindStr /BIR ".....R"&& ATTRIB -R -A -S -H *.* /S /D
ATTRIB "SYSTEM"|>Nul FindStr /BIR ".....R"&& ATTRIB -R -A -S -H *.* /S /D
ATTRIB "DISTR\BIS"|>Nul FindStr /BIR ".....R"&& ATTRIB -R -A -S -H *.* /S /D
ECHO ОК!
REM ##################################################################################################################################################
ECHO ПРОВЕРКА НАЛИЧИЯ БАЗОВЫХ МОДУЛЕЙ...
ECHO ОЖИДАЙТЕ...
IF "%ZM%"=="ОТСУТСТВ" (
   COLOR CF
   ECHO ===============================================================================
   ECHO =                  Отсутствует Запускаемый Модуль программы.                  =
   ECHO =                   Установите CONS.EXE и повторите запуск.                   =
   ECHO ===============================================================================
   PAUSE
   EXIT
   )
IF "%RES%"=="ОТСУТСТВУЕТ!" (
   COLOR CF
   ECHO ===============================================================================
   ECHO =                Отсутствует Технологический Модуль программы.                =
   ECHO =                     Установите RES и повторите запуск.                      =
   ECHO ===============================================================================
   PAUSE
   EXIT
   )
SET TVR=1false1
SET HTR=2false2
SET SHR=3false3
IF EXIST VR*.RES SET TVR=TRUE
IF EXIST HT*.RES SET HTR=TRUE
IF EXIST SH*.RES SET SHR=TRUE
IF %TVR%==%HTR% SET MENU1=TRUE
IF %TVR%==%SHR% SET MENU1=TRUE
IF %HTR%==%SHR% SET MENU1=TRUE
IF %MENU1%==TRUE (
   COLOR CF
   ECHO ===============================================================================
   ECHO =   У вас в комплекте несколько технологических модулей *.RES разных типов!   =
   ECHO = Для работы оставьте только один, соответствующий вашим дистрибутивам *.DIN. =
   ECHO = Для стандартного пользовательского комплекта К+ ТМ должен быть VR401###.RES =
   ECHO ===============================================================================
   PAUSE
   EXIT
   )
IF NOT EXIST DISTR\DIN\*.DIN (
   COLOR CF
   ECHO ===============================================================================
   ECHO =                    Отсутствуют дистрибутивы [DIN файлы].                    =
   ECHO =          Не забудьте установить DIN файлы для продолжения работы!           =
   ECHO ===============================================================================
   PAUSE
   EXIT
   )
IF NOT EXIST SYSTEM\*.TOR (
   COLOR CF
   ECHO ===============================================================================
   ECHO =                     Не найдены важные системные файлы.                      =
   ECHO =           Установите корректную директорию SYSTEM для работы К+.            =
   ECHO ===============================================================================
   PAUSE
   EXIT
   )
IF NOT EXIST SYSTEM\*.CFG (
   COLOR CF
   ECHO ===============================================================================
   ECHO =                     Не найдены важные системные файлы.                      =
   ECHO =           Установите корректную директорию SYSTEM для работы К+.            =
   ECHO ===============================================================================
   PAUSE
   EXIT
   )
SET MENU1=0
ECHO ОК!
REM ##################################################################################################################################################
ECHO ПРОВЕРКА НАЛИЧИЯ УСТАНОВЛЕННЫХ ИБ...
ECHO ОЖИДАЙТЕ...
CD BASE
FOR /D %%n in (*) do (
  IF EXIST %%n\*.KUB SET MENU1=TRUE
  )
CD ..
IF NOT "%MENU1%"=="TRUE" (
   COLOR CF
   ECHO ===============================================================================
   ECHO =                 Не установлено ни одной информационной базы.                =
   ECHO =    Установите ИБ в каталог BASE и пропишите в BASELIST.CFG для работы К+.   =
   ECHO ===============================================================================
   PAUSE
   EXIT
   )
SET MENU1=0
ECHO ОК!
REM ##################################################################################################################################################
IF NOT "%REGTEST%"=="1" SET REGFLAG=1
IF "%REGTEST%"=="1" (
   ECHO ПРОВЕРКА РЕГИСТРАЦИИ ДИСТРИБУТИВОВ...
   ECHO ОЖИДАЙТЕ...
   IF EXIST RECEIVE\*.USR (
      MD RECEIVE\TMP   >nul 2>&1
      MOVE /Y RECEIVE\*.USR RECEIVE\TMP   >nul 2>&1
      )
   IF NOT EXIST DISTR\BIS\*.BIS (
      COLOR CF
      ECHO ===============================================================================
      ECHO =                Обнаружено, что система не зарегистрирована.                 =
      ECHO =           Для работы программы необходимо выполнить регистрацию.            =
      ECHO =        Воспользуйтесь пунктами меню № 3X для регистрации программы.         =
      ECHO ===============================================================================
      GOTO REGFLAG0
      )
   IF EXIST RECEIVE\*.USR DEL /q /f RECEIVE\*.USR
   %STRT1% %CONS% /ADM /USR /NORUNNER+ /NOREINDEX0 /YES
   IF EXIST RECEIVE\*.USR (
      DEL /q /f RECEIVE\*.USR
      ECHO ОК!
      SET REGFLAG=1
      ) ELSE (
      COLOR 0E
      ECHO ===============================================================================
      ECHO =     Обнаружено, что регистрационный файл не соответствует вашей системе.    =
      ECHO =         Для работы программы необходимо выполнить перерегистрацию.          =
      ECHO =        Воспользуйтесь пунктами меню № 3X для регистрации программы.         =
      ECHO ===============================================================================
      :REGFLAG0
      SET REGFLAG=0
      PAUSE
      )
   IF EXIST RECEIVE\TMP\*.USR (
      MOVE /Y RECEIVE\TMP\*.USR RECEIVE   >nul 2>&1
      RD /s /q RECEIVE\TMP   >nul 2>&1
      )
   )
REM ##################################################################################################################################################
CLS
ECHO ===============================================================================
ECHO ====    -= 1/2/3/4/5/6 - выбор модуля для работы/выполнения операций =-    ====
:starttmp
ECHO ====   -= RU-BOARD.COM =-  ###  -= %DAT% =-  ###  -= RU-BOARD.COM =-  ====
ECHO ====  -= A1eksandr1 =-  ### -= FORUM.RU-BOARD.COM =-  ### -= A1eksandr1 =- ====
IF "%REGFLAG%"=="0" ECHO ==== -= ВНИМАНИЕ! Система К+ не зарегистрирована! ВЫПОЛНИТЕ ОПЕРАЦИЮ 3X =- ====
IF "%REGFLAG%"=="1" ECHO ===============================================================================
ECHO = 11 - Запуск без ключей        ...Запускающий Модуль: %ZM%         # 1 # =
ECHO = 12 - Запуск с ключом ADM      ...Технолог-ий Модуль: %RES%     # 2 # =
     SET RPP=
     IF "%RESP%"=="%RES%" SET RPP=  
ECHO = 13 - Запуск с ключом GROUP    .........Патченный ТМ: %RESP% %RPP%  # 3 # =
ECHO = 14 - Запуск с ключом SYSTEM   ...............Лоадер: %LDR%     # 4 # =
ECHO = 15 - Запуск с ключом TEST     ...............ОнЛайн: %RESONL% #5/6# =
ECHO ===============================================================================
ECHO = 21 - Стандартное обновление ИБ                     = %xos% SYSTEM для: %SYS% ИБ =
ECHO = 22 - Стандартное обновление ИБ [пакетный режим]    ==========================
ECHO = 23 - Обновление ИБ с перерегистрацией с тек РицИД                           =
ECHO = 24 - Обновление ИБ с перерегистрацией с тек РицИД [пакетный режим]          =
ECHO = 25 - Последовательность операций - Обновление ИБ - Сжатие ИБ                =
ECHO = 26 - Последовательность операций - Перерегистрация - Обновление - Сжатие    =
ECHO = 27 - Сформировать запросы по всем базам на пополнение   [в директории SEND] =
ECHO = 28 - Запустить утилиту-помощник формирования запросов по ИБ с пропусками    =
ECHO ===============================================================================
ECHO = 31 - Создать файлы запросов на регистрацию для всех ИБ комплекта            =
ECHO = 32 - Зарегистрировать систему через файлы запросов / ответов / ввод ключей  =
ECHO = 33 - Запустить генератор ключей и файлов-ответов на регистрацию             =
ECHO = 34 - Зарегистрировать систему генератором ключей с текущим РицИД [Save ANS] =
ECHO = 35 - Зарегистрировать систему генератором ключей с заданным РицИД [Del?ANS] =
ECHO ===============================================================================
ECHO = 40 - Сформировать объединенные словари                                      =
ECHO = 41 - Сжатие всех баз [запуск с ключом COMPRESS]             [410 - error +] =
ECHO = 42 - Тестирование всех баз [без исправления ошибок]         [420 - error +] =
ECHO = 43 - Тестирование всех баз [с исправлением ошибок]          [430 - error +] =
ECHO = 44 - Переиндексация всех баз [запуск с ключом REINDEX]      [440 - error +] =
ECHO = 45 - Сжатие и переиндексация всех баз [длительный процесс]  [450 - error +] =
ECHO = 46 - Формирование, редактирование BASELIST.CFG    [подменю с выбором опций] =
ECHO = 47 - Зеркальный комплект. Транзакционное фоновое пополнение [п о д м е н ю] =
ECHO ===============================================================================
ECHO = 51 - Отключить всех работающих с комплектом пользователей                   =
ECHO = 52 - Очистка директорий RECEIVE/SEND/USERS и файлов RECEIVE.INF             =
ECHO = 53 - Удаление всех пользовательских и регистрационных данных                =
ECHO = 54 - Удаление записей из реестра о К+, путей к профайлам юзера              =
ECHO = 55 - Заблокировать доступ к xxxxx.consultant.ru [в файле hosts] WXP-W10     =
ECHO = 56 - Сформировать служебный файл статистики *.usr в директории RECEIVE      =
ECHO = 57 - Сформировать файл статистики LAST_COMP.TXT по структуре комплекта К+   =
ECHO = 58 - Собрать основную информацию о комплекте К+ и ПК в файл SERVICEINFO.ZIP =
IF /I "%RES:~0,-10%"=="VR" (
   ECHO ==================================================== Тех. тип: ПОЛЬЗОВАТЕЛЬ ===
   )
IF /I "%RES:~0,-10%"=="HT" (
   ECHO ============================================ Тех. тип: ИНФОРМАЦИОННЫЙ ЦЕНТР ===
   ECHO = 61 - Сформировать пополнения по запросу                                     =
   )
IF /I "%RES:~0,-10%"=="SH" (
   ECHO ================================================ Тех. тип: АДМИНИСТРАТОР ИБ ===
   ECHO = 61 - Сформировать пополнения по запросу                                     =
   )
ECHO ===============================================================================
ECHO = 00 - Выход [неверный ввод] = [000 - ReLoad]  =  [30.03.2020] v3.5.3.9 lite  =
ECHO ===============================================================================
SET /p MENU1=Введите номер варианта запуска и нажмите клавишу ENTER: 
CLS
ECHO ===============================================================================
ECHO  =                   Выполняется операция № %MENU1%! Ожидайте...                  =
ECHO ===============================================================================

IF "%MENU1%"=="0" EXIT
IF "%MENU1%"=="00" EXIT
IF "%MENU1%"=="000" GOTO start

IF "%MENU1%"=="1" (
   CLS
   SET CONS=%ZM%
   COLOR 1A
   ECHO ===============================================================================
   ECHO ====   -= ВНИМАНИЕ! Для работы принудительно выбран запускаемый модуль =-  ====
   GOTO starttmp
   )
IF "%MENU1%"=="2" (
   CLS
   SET CONS=%RES%
   COLOR 1B
   ECHO ===============================================================================
   ECHO ====  -= ВНИМАНИЕ! Для работы принудительно выбран технолог-кий модуль =-  ====
   GOTO starttmp
   )
IF "%MENU1%"=="3" (
   CLS
   IF "%RESP%"=="НЕОПРЕДЕЛЕН!!!" (
      COLOR CF
      ECHO Отсутствует патченный ТМ в директории К+.
      ECHO Установите его и повторите запуск.
      PAUSE
      GOTO start
      )
   SET CONS=%RESP%
   COLOR 0A
   ECHO ===============================================================================
   ECHO ====      -= ВНИМАНИЕ! Для работы принудительно выбран патченный ТМ =-     ====
   GOTO starttmp
   )
IF "%MENU1%"=="4" (
   CLS
   IF "%LDR%"=="НЕОПРЕДЕЛЕН!" (
      COLOR CF
      ECHO Отсутствует лоадер в директории К+.
      ECHO Установите его и повторите запуск.
      PAUSE
      GOTO start
      )
   SET CONS=%LDR%
   COLOR 0B
   ECHO ===============================================================================
   ECHO ====         -= ВНИМАНИЕ! Для работы принудительно выбран лоадер =-        ====
   GOTO starttmp
   )
IF "%MENU1%"=="5" (
   CLS
   IF "%RESONL%"=="ОТСУТСТВ" (
      COLOR CF
      ECHO Отсутствует патченный ОнЛайн ТМ в директории К+.
      ECHO Установите его и повторите запуск.
      PAUSE
      GOTO start
      )
   SET CONS=%RESONL%
   COLOR 0F
   ECHO ===============================================================================
   ECHO ====  -= ВНИМАНИЕ! Для работы принудительно выбран ТМ с ОнЛайн доступом =- ====
   GOTO starttmp
   )
IF "%MENU1%"=="6" (
   CLS
   IF "%RESRLN%"=="ОТСУТСТВ" (
      COLOR CF
      ECHO Отсутствует патченный RemЛайн ТМ в директории К+.
      ECHO Установите его и повторите запуск.
      PAUSE
      GOTO start
      )
   SET CONS=%RESRLN%
   COLOR 0F
   ECHO ===============================================================================
   ECHO ==== -= ВНИМАНИЕ! Для работы принудительно выбран ТМ с RemЛайн доступом =- ====
   GOTO starttmp
   )

IF "%MENU1%"=="11" %STRT2% %CONS%
IF "%MENU1%"=="12" %STRT2% %CONS% /ADM
IF "%MENU1%"=="13" %STRT2% %CONS% /GROUP
IF "%MENU1%"=="14" %STRT2% %CONS% /ADM /SYSTEM
IF "%MENU1%"=="15" (
   COLOR 2F
   %STRT1% %ZM% /TEST
   GOTO start
   )


IF "%MENU1%"=="21" (
   IF %REGFLAG%==0 CALL :REGFLAG1
   CALL :testans0
   CALL :testans1
   ECHO ВЫПОЛНЯЕТСЯ ПОПОЛНЕНИЕ ИБ...
   ECHO ОЖИДАЙТЕ...
   COLOR 2F
   %STRT1% %CONS% /ADM /RECEIVE /BASE* /NORUNNER
   ECHO ОК!
   CALL :testans2
   CALL :testhost
   GOTO start
   )
IF "%MENU1%"=="22" (
   IF %REGFLAG%==0 CALL :REGFLAG1
   CALL :testans0
   CALL :testans1
   ECHO ВЫПОЛНЯЕТСЯ ПОПОЛНЕНИЕ ИБ...
   ECHO ОЖИДАЙТЕ...
   COLOR 2F
   %STRT1% %CONS% /ADM /RECEIVE /BASE* /NORUNNER+ /YES
   ECHO ОК!
   CALL :testans2
   CALL :testhost
   GOTO start
   )
IF "%MENU1%"=="23" (
   CALL :testans0
   CALL :testans1
   ECHO ВЫПОЛНЯЕТСЯ ПОПОЛНЕНИЕ ИБ...
   ECHO ОЖИДАЙТЕ...
   COLOR 2F
   CALL :registr
   %STRT1% %CONS% /ADM /RECEIVE /BASE* /NORUNNER
   ECHO ОК!
   CALL :testans2
   CALL :testhost
   GOTO start
   )
IF "%MENU1%"=="24" (
   CALL :testans0
   CALL :testans1
   ECHO ВЫПОЛНЯЕТСЯ ПОПОЛНЕНИЕ ИБ...
   ECHO ОЖИДАЙТЕ...
   COLOR 2F
   CALL :registr
   %STRT1% %CONS% /ADM /RECEIVE /BASE* /NORUNNER+ /YES
   ECHO ОК!
   CALL :testans2
   CALL :testhost
   GOTO start
   )
IF "%MENU1%"=="25" (
   IF %REGFLAG%==0 CALL :REGFLAG1
   CALL :testans0
   CALL :testans1
   ECHO ВЫПОЛНЯЕТСЯ ПОПОЛНЕНИЕ ИБ...
   ECHO ОЖИДАЙТЕ...
   COLOR 2F
   %STRT1% %CONS% /ADM /RECEIVE /BASE* /NORUNNER /YES
   ECHO ОК!
   ECHO ВЫПОЛНЯЕТСЯ СЖАТИЕ ИБ...
   ECHO ОЖИДАЙТЕ...
   %STRT1% %CONS% /ADM /COMPRESS /BASE* /NORUNNER /YES
   ECHO ОК!
   CALL :testans2
   CALL :testhost
   GOTO start
   )
IF "%MENU1%"=="26" (
   CALL :testans0
   CALL :testans1
   COLOR 2F
   CALL :registr
   ECHO ВЫПОЛНЯЕТСЯ ПОПОЛНЕНИЕ ИБ...
   ECHO ОЖИДАЙТЕ...
   %STRT1% %CONS% /ADM /RECEIVE /BASE* /NORUNNER /YES
   ECHO ОК!
   ECHO ВЫПОЛНЯЕТСЯ СЖАТИЕ ИБ...
   ECHO ОЖИДАЙТЕ...
   %STRT1% %CONS% /ADM /COMPRESS /BASE* /NORUNNER /YES
   ECHO ОК!
   CALL :testans2
   CALL :testhost
   GOTO start
   )
IF "%MENU1%"=="27" (
   IF %REGFLAG%==0 CALL :REGFLAG1
   COLOR 2F
   %STRT1% %CONS% /ADM /QUEST /BASE* /NORUNNER
   GOTO start
   )
IF "%MENU1%"=="28" (
   %STRT1% CRQT.EXE
   GOTO start
   )


IF "%MENU1%"=="31" (
   COLOR 2F
   %STRT1% %CONS% /ADM /MAKEQR
   GOTO start
   )
IF "%MENU1%"=="32" (
   COLOR 2F
   %STRT1% %CONS% /ADM /REG*
   GOTO start
   )
IF "%MENU1%"=="33" (
   CALL :testkgreg
   %STRT1% CREG.EXE
   GOTO start
   )
IF "%MENU1%"=="34" (
   CALL :registr
   GOTO start
   )
IF "%MENU1%"=="35" (
   COLOR 2F
   CLS
   CALL :testkgreg
   ECHO Внимание! Сейчас запустится генератор ответов.
   ECHO При необходимости смените текущий РИЦИД на требуемый Вам.
   ECHO Нажмите в KeyGen-е кнопку "Зарегистрировать".
   ECHO Дождитесь появления окна с надписью в центре "Все системы зарегистрированы **".
   ECHO Нажмите в этом окне кнопку "Закрыть".
   ECHO Подождите 5-30 сек для формирования USR-файла.
   ECHO Закройте окно KeyGen-а. Регистрация завершена!
   PAUSE
   DEL /q /f ADM\*.*
   RD /s /q ADM\STS
   DEL /q /f DISTR\BIS\*.*
   DEL /q /f RECEIVE\*.AR
   DEL /q /f SEND\*.QR
   %STRT1% CREG.EXE
   GOTO start
   )


IF "%MENU1%"=="40" (
   IF %REGFLAG%==0 CALL :REGFLAG1
   COLOR 2F
   IF EXIST BASE\COMMON RD /s /q BASE\COMMON
   %STRT1% %CONS% /ADM /REINDEX0
   GOTO start
   )   
IF "%MENU1%"=="41" %STRT2% %CONS% /ADM /COMPRESS /BASE* /NORUNNER /YES
IF "%MENU1%"=="42" %STRT2% %CONS% /ADM /BASETEST- /BASE* /NORUNNER /YES
IF "%MENU1%"=="43" %STRT2% %CONS% /ADM /BASETEST /BASE* /NORUNNER /YES
IF "%MENU1%"=="44" %STRT2% %CONS% /ADM /REINDEX /BASE* /NORUNNER /YES
IF "%MENU1%"=="45" (
   IF %REGFLAG%==0 CALL :REGFLAG1
   COLOR 2F
   ECHO ИДЁТ СЖАТИЕ ИНФОРМАЦИОННЫХ БАЗ...
   ECHO ОЖИДАЙТЕ...
   %STRT1% %CONS% /ADM /COMPRESS /BASE* /NORUNNER /YES
   ECHO ОК!
   ECHO ИДЁТ ПЕРЕИНДЕКСАЦИЯ ИНФОРМАЦИОННЫХ БАЗ...
   ECHO ОЖИДАЙТЕ...
   %STRT1% %CONS% /ADM /REINDEX /BASE* /NORUNNER /YES
   ECHO ОК!
   GOTO start
   )
IF "%MENU1%"=="410" %STRT2% %CONS% /ADM /COMPRESS /BASE* /NORUNNER
IF "%MENU1%"=="420" %STRT2% %CONS% /ADM /BASETEST- /BASE* /NORUNNER
IF "%MENU1%"=="430" %STRT2% %CONS% /ADM /BASETEST /BASE* /NORUNNER
IF "%MENU1%"=="440" %STRT2% %CONS% /ADM /REINDEX /BASE* /NORUNNER
IF "%MENU1%"=="450" (
   IF %REGFLAG%==0 CALL :REGFLAG1
   COLOR 2F
   ECHO ИДЁТ СЖАТИЕ ИНФОРМАЦИОННЫХ БАЗ...
   ECHO ОЖИДАЙТЕ...
   %STRT1% %CONS% /ADM /COMPRESS /BASE* /NORUNNER
   ECHO ОК!
   ECHO ИДЁТ ПЕРЕИНДЕКСАЦИЯ ИНФОРМАЦИОННЫХ БАЗ...
   ECHO ОЖИДАЙТЕ...
   %STRT1% %CONS% /ADM /REINDEX /BASE* /NORUNNER
   ECHO ОК!
   GOTO start
   )
IF "%MENU1%"=="46" GOTO editbl
IF "%MENU1%"=="47" GOTO BTR


IF "%MENU1%"=="51" (
   IF %REGFLAG%==0 CALL :REGFLAG1
   COLOR 2F
   %STRT1% %CONS% /ADM /OFF
   GOTO start
   )
IF "%MENU1%"=="52" (
   COLOR 2F
   IF EXIST RECEIVE\*.*               DEL /q /f RECEIVE\*.*
   IF EXIST SEND\*.*                  DEL /q /f SEND\*.*
   IF EXIST USERS\*.*                 DEL /q /f USERS\*.*
                                      DEL /q /f /s BASE\RECEIVE.INF
   IF EXIST CONS_ERR.TXT              DEL /q /f CONS_ERR.TXT
   IF EXIST CONS_INET.TXT             DEL /q /f CONS_INET.TXT
   IF EXIST CONS_INET_LISTFILES.TXT   DEL /q /f CONS_INET_LISTFILES.TXT
   IF EXIST CONS_LOG.TXT              DEL /q /f CONS_LOG.TXT
   IF EXIST *.LOG                     DEL /q /f *.LOG
   IF EXIST ADM\STS                   RD /s /q ADM\STS
   GOTO start
   )
IF "%MENU1%"=="53" (
   COLOR 2F
   IF EXIST RECEIVE\*.*               DEL /q /f RECEIVE\*.*
   IF EXIST SEND\*.*                  DEL /q /f SEND\*.*
   IF EXIST USERS\*.*                 DEL /q /f USERS\*.*
                                      DEL /s /q /f BASE\RECEIVE.INF
   IF EXIST CONS_ERR.TXT              DEL /q /f CONS_ERR.TXT
   IF EXIST CONS_INET.TXT             DEL /q /f CONS_INET.TXT
   IF EXIST CONS_INET_LISTFILES.TXT   DEL /q /f CONS_INET_LISTFILES.TXT
   IF EXIST CONS_LOG.TXT              DEL /q /f CONS_LOG.TXT
   IF EXIST *.LOG                     DEL /q /f *.LOG
   IF EXIST ADM\STS                   RD /s /q ADM\STS
   IF EXIST CONS.CFG                  RD /s /q CONS.CFG
   IF EXIST *.dmp                     DEL /q /f *.dmp
   IF EXIST *.scr                     DEL /q /f *.scr
   IF EXIST ADM\*.*                   DEL /q /f ADM\*.*
   IF EXIST DISTR\BIS\*.*             DEL /q /f DISTR\BIS\*.*
   IF EXIST DISTR\UIN\*.*             DEL /q /f DISTR\UIN\*.*
   GOTO start
   )
IF "%MENU1%"=="54" (
   COLOR 2F
   REG DELETE "HKCU\Software\ConsultantPlus" /f
   GOTO start
   )
IF "%MENU1%"=="55" (
   COLOR 2F
   FIND "#	ConsultantPlus lock services VMI NPO" < %systemroot%\system32\drivers\etc\hosts ||	ECHO #	ConsultantPlus lock services VMI NPO>> %systemroot%\system32\drivers\etc\hosts
   FIND "www1.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		www1.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "www2.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		www2.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "base1.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		base1.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "base2.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		base2.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "cl1.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		cl1.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "cl2.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		cl2.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "client.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		client.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "cpcd.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		cpcd.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "cpcda.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		cpcda.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "lite.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		lite.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "arb.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		arb.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "aoas.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		aoas.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "soj.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		soj.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "astn.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		astn.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "ammo.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		ammo.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "consult1.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		consult1.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "consult2.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		consult2.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   FIND "consult3.consultant.ru" < %systemroot%\system32\drivers\etc\hosts ||	ECHO 	127.0.0.1		consult3.consultant.ru>> %systemroot%\system32\drivers\etc\hosts
   ECHO Проверьте наличие записей вида 127.0.0.1 xxxxx.consultant.ru в hosts и закройте блокнот!
   %STRT1% notepad.exe %systemroot%\system32\drivers\etc\hosts
   GOTO start
   )
IF "%MENU1%"=="56" (
   IF %REGFLAG%==0 CALL :REGFLAG1
   COLOR 2F
   %STRT1% %CONS% /ADM /USR
   goto start
   )
IF "%MENU1%"=="57" (
   COLOR 2F
   IF exist SYSTEM.LST DEL /q /f SYSTEM.LST
   %STRT1% %CONS% /ADM /REVLIST
   IF EXIST LAST_COMP.TXT DEL /q /f LAST_COMP.TXT
   IF EXIST BASE\BASELIST.CFG ECHO ===============================================================================>> LAST_COMP.TXT
   IF EXIST BASE\BASELIST.CFG ECHO =                        Содержание файла BASELIST.CFG:                       =>> LAST_COMP.TXT
   IF EXIST BASE\BASELIST.CFG ECHO ===============================================================================>> LAST_COMP.TXT
   IF EXIST BASE\BASELIST.CFG COPY /b LAST_COMP.TXT + BASE\BASELIST.CFG LAST_COMP.TXT
   IF EXIST BASE\BASELIST.CFG ECHO.>> LAST_COMP.TXT
   IF EXIST BASE\BASELIST.CFG ECHO.>> LAST_COMP.TXT
   IF EXIST BASE\COMPLECT.CFG ECHO ===============================================================================>> LAST_COMP.TXT
   IF EXIST BASE\COMPLECT.CFG ECHO =                        Содержание файла COMPLECT.CFG:                       =>> LAST_COMP.TXT
   IF EXIST BASE\COMPLECT.CFG ECHO ===============================================================================>> LAST_COMP.TXT
   IF EXIST BASE\COMPLECT.CFG COPY /b LAST_COMP.TXT + BASE\COMPLECT.CFG LAST_COMP.TXT
   IF EXIST BASE\COMPLECT.CFG ECHO.>> LAST_COMP.TXT
   IF EXIST BASE\COMPLECT.CFG ECHO.>> LAST_COMP.TXT
   IF EXIST BASE\TIMEOUT.CFG ECHO ===============================================================================>> LAST_COMP.TXT
   IF EXIST BASE\TIMEOUT.CFG ECHO =                        Содержание файла TIMEOUT.CFG:                        =>> LAST_COMP.TXT
   IF EXIST BASE\TIMEOUT.CFG ECHO ===============================================================================>> LAST_COMP.TXT
   IF EXIST BASE\TIMEOUT.CFG COPY /b LAST_COMP.TXT + BASE\TIMEOUT.CFG LAST_COMP.TXT
   IF EXIST BASE\TIMEOUT.CFG ECHO.>> LAST_COMP.TXT
   IF EXIST BASE\TIMEOUT.CFG ECHO.>> LAST_COMP.TXT
   IF EXIST START.KEY ECHO ===============================================================================>> LAST_COMP.TXT
   IF EXIST START.KEY ECHO =                         Содержание файла START.KEY:                         =>> LAST_COMP.TXT
   IF EXIST START.KEY ECHO ===============================================================================>> LAST_COMP.TXT
   IF EXIST START.KEY COPY /b LAST_COMP.TXT + START.KEY LAST_COMP.TXT
   IF EXIST START.KEY ECHO.>> LAST_COMP.TXT
   IF EXIST START.KEY ECHO.>> LAST_COMP.TXT
   ECHO ===============================================================================>> LAST_COMP.TXT
   ECHO =           Иерархическая структура каталогов и файлов комплекта К+:          =>> LAST_COMP.TXT
   ECHO ===============================================================================>> LAST_COMP.TXT
   DIR /s >>LAST_COMP.TXT
   ECHO ===============================================================================>> LAST_COMP.TXT
   ECHO.>> LAST_COMP.TXT
   ECHO.>> LAST_COMP.TXT
   IF EXIST DISTR\DIN\*.DIN ECHO ===============================================================================>> LAST_COMP.TXT
   IF EXIST DISTR\DIN\*.DIN ECHO =                  Содержание дистрибутивов DISTR\DIN\*.DIN:                  =>> LAST_COMP.TXT
   IF EXIST DISTR\DIN\*.DIN ECHO ===============================================================================>> LAST_COMP.TXT
   IF EXIST DISTR\DIN\*.DIN COPY /b LAST_COMP.TXT + DISTR\DIN\*.DIN LAST_COMP.TXT
   IF EXIST DISTR\DIN\*.DIN ECHO ===============================================================================>> LAST_COMP.TXT
   IF EXIST DISTR\DIN\*.DIN ECHO.>> LAST_COMP.TXT
   IF EXIST DISTR\DIN\*.DIN ECHO.>> LAST_COMP.TXT
   GOTO start
   )
IF "%MENU1%"=="58" (
   COLOR 2F
   %STRT1% %CONS% /SERVICEINFO
   IF EXIST inet.log DEL /q /f inet.log
   GOTO start
   )


IF "%MENU1%"=="61" (
   IF %REGFLAG%==0 CALL :REGFLAG1
   COLOR 2F
   CALL :testrgt0
   CALL :testqst0
   %STRT1% %CONS% /ADM /ANSWER /BASE* /NOREINDEX0
   CALL :testqst1
   goto start
   )
GOTO prop


:testans0
REM Проверка наличия ANSов и снятие с них атрибута "Только для чтения" и иных
ECHO ПРОВЕРКА НАЛИЧИЯ ОБНОВЛЕНИЙ И КОРРЕКТИРОВКА АТРИБУТОВ...
ECHO ОЖИДАЙТЕ...
IF NOT EXIST RECEIVE\*.ANS (
   COLOR CF
   ECHO ===============================================================================
   ECHO =       Внимание, в директории RECEIVE отсутствуют ANS файлы пополнений!      =
   ECHO =   Обновление невозможно! Скопируйте *.ANS в RECEIVE и повторите операцию.   =
   ECHO = Файлы нужно помещать в распакованном виде [не архивированные, не в папках!] =
   ECHO ===============================================================================
   PAUSE
   GOTO start
   )
ATTRIB -R -A -S -H RECEIVE\*.ANS
ECHO ОК!
REM Проверка прав на запись к файлам баз данных, корректировка при необходимости
ECHO ПРОВЕРКА И КОРРЕКТИРОВКА ПРАВ НА ЗАПИСЬ В ФАЙЛЫ БАЗ ДАННЫХ...
ECHO ОЖИДАЙТЕ...
ATTRIB -R -A -S -H BASE\*.* /S /D
ECHO ОК!
GOTO :eof


:testans1
REM Проверка соответствия пополнений установленным в комплект ИБ
ECHO ПРОВЕРКА СООТВЕТСТВИЯ ОБНОВЛЕНИЙ УСТАНОВЛЕННЫМ ИБ...
ECHO ОЖИДАЙТЕ...
SET TSTGLOBAL=0
FOR /f "tokens=1 delims=#" %%a in ('dir /b /a-d RECEIVE\*.ANS ^| findstr /i /v "CONS.*.ANS"') do (
   SET TST=0
   FOR /f "tokens=* delims=" %%b in ('findstr /i /b "." "BASE\BASELIST.CFG"') do (
      IF /I "%%~a"=="%%~b" SET TST=1
      )
   SET ANS=%%~a
   CALL :TSTADD
   )
IF "%TSTGLOBAL%"=="1" (
   REM COLOR CF
   ECHO ===============================================================================
   ECHO =    В каталоге RECEIVE обнаружены неподходящие для вашего комплекта ANS!     =
   ECHO =   То есть у Вас отсутствуют ИБ, для которых предназначены эти обновления!   =
   ECHO =    Они не будут приняты и после обновления останутся в каталоге RECEIVE!    =
   ECHO ===============================================================================
   PAUSE
   )
ECHO ОК!
GOTO :eof
:TSTADD
IF /I "%ANSOLD%"=="%ANS%" SET TST=1
SET ANSOLD=%ANS%
IF "%TST%"=="0" (
   ECHO ! Для файлов пополнения %ANS%#*#*.ANS в комплекте отсутствует ИБ %ANS% !
   SET TSTGLOBAL=1
   )
GOTO :eof


:testans2
REM Проверка непринятых ANSов по причине отсутствия ИБ и иных
ECHO ВЫПОЛНЯЕТСЯ ПРОВЕРКА НЕПРИНЯТЫХ ОБНОВЛЕНИЙ...
ECHO ОЖИДАЙТЕ...
IF EXIST RECEIVE\*.ANS (
   REM COLOR CF
   ECHO ===============================================================================
   ECHO =                    Поиск непринятых файлов обновления...                    =
   ECHO =   Внимание, в директории RECEIVE остались непринятые ANS файлы пополнений   =
   ECHO =             Возможно у вас просто отсутствуют в комплекте эти ИБ            =
   ECHO =                 Либо в процессе пополнения произошли ошибки                 =
   ECHO =             Обратите внимание на оставшиеся файлы ANS в RECEIVE             =
   ECHO ===============================================================================
   PAUSE
   )
ECHO ОК!
GOTO :eof


:testhost
REM Проверка наличия пропусков только в обновившихся ИБ
ECHO ВЫПОЛНЯЕТСЯ ПРОВЕРКА НАЛИЧИЯ ПРОПУСКОВ...
ECHO ОЖИДАЙТЕ...
SET i=0
SET ii=0
FOR /f "skip=2 tokens=1 delims=," %%i in ('find "#HOST" RECEIVE\LAST_REC.TXT') do SET i=1
IF %i%==1 (
   COLOR CF
   ECHO ===============================================================================
   ECHO = Проверка ровности пополненных ИБ...                                         =
   ECHO = Внимание! Обнаружены неровно пополненные ИБ:                                =
   FOR /f "skip=2 tokens=1 delims=," %%i in ('find "#HOST" RECEIVE\LAST_REC.TXT') do ECHO = ### %%i
   ECHO = Примите пропущенные обновления либо сформируйте запрос на пополнение!       =
   ECHO = Сформировать запрос на пополнение только для неполных ИБ [y-Да; n-Нет]?     =
   ECHO ===============================================================================
   SET /p ii=
   )
IF /I %ii%==y (
   IF EXIST SEND\*.QST DEL /q /f SEND\*.QST
   ECHO ===============================================================================
   ECHO = Выполняется формирование запросов. Ожидайте...                              =
   FOR /f "skip=2 tokens=1 delims=," %%i in ('find "#HOST" RECEIVE\LAST_REC.TXT') do %STRT1% CONS.EXE /ADM /QUEST /BASE_%%i
   ECHO = Формирование завершено. Запросы созданы в директории SEND.                  =
   ECHO ===============================================================================
   PAUSE
   )
ECHO ОК!
GOTO :eof


:registr
CALL :testkgarg
ECHO ВЫПОЛНЯЕТСЯ РЕГИСТРАЦИЯ КОМПЛЕКТА КОНСУЛЬТАНТ ПЛЮС...
ECHO ОЖИДАЙТЕ...
IF EXIST RECEIVE\*.ANS (
   MD RECEIVE\TMP
   MOVE /Y RECEIVE\*.ANS RECEIVE\TMP
   )
IF EXIST ADM\*.ADM     DEL /q /f ADM\*.*
RD /s /q ADM\STS
IF EXIST DISTR\BIS\*.* DEL /q /f DISTR\BIS\*.*
IF EXIST RECEIVE\*.AR  DEL /q /f RECEIVE\*.AR
IF EXIST SEND\*.QR     DEL /q /f SEND\*.QR
%STRT1% CRGA.EXE
IF EXIST RECEIVE\*.AR  DEL /q /f RECEIVE\*.AR
IF EXIST SEND\*.QR     DEL /q /f SEND\*.QR
IF EXIST RECEIVE\TMP\*.ANS (
   MOVE /Y RECEIVE\TMP\*.ANS RECEIVE
   RD /s /q RECEIVE\TMP
   )
SET REGFLAG=1
ECHO ОК!
GOTO :eof


:testkgarg
IF NOT EXIST CRGA.EXE (
   COLOR CF
   CLS
   ECHO ===============================================================================
   ECHO =  Внимание, в директории К+ отсутствует автоматический регистратор CRGA.EXE! =
   ECHO =     Выполнение операции невозможно. Установите регистратор и повторите.     =
   ECHO ===============================================================================
   PAUSE
   GOTO start
   )
GOTO :eof


:testkgreg
IF NOT EXIST CREG.EXE (
   COLOR CF
   CLS
   ECHO ===============================================================================
   ECHO =      Внимание, в директории К+ отсутствует генератор ответов CREG.EXE!      =
   ECHO =     Выполнение операции невозможно. Установите регистратор и повторите.     =
   ECHO ===============================================================================
   PAUSE
   GOTO start
   )
IF NOT EXIST CREG.DLL (
   COLOR CF
   CLS
   ECHO ===============================================================================
   ECHO =  Внимание, в директории К+ отсутствует библиотека генератора отв. CREG.DLL! =
   ECHO =     Выполнение операции невозможно. Установите регистратор и повторите.     =
   ECHO ===============================================================================
   PAUSE
   GOTO start
   )
GOTO :eof


:editbl
COLOR B0
TITLE Формирование, редактирование BASELIST.CFG
SET MENU1=0
MODE CON COLS=%WINDOWCOLS% LINES=%WINDOWLINES%
SET FILE=BASELIST.CFG
SET IB=XXXXX
CLS
ECHO ===============================================================================
ECHO = 1 - Сформировать список ИБ %FILE% по BASE                             =
ECHO = 2 - Добавить заданную далее ИБ в список %FILE%                        =
ECHO = 3 - Удалить заданную далее ИБ из списка %FILE%                        =
ECHO = 4 - Добавить ИБ из переменной IB в список %FILE%                      =
ECHO = 5 - Удалить ИБ из переменной IB из списка %FILE%                      =
ECHO = 6 - Вывести список всех прописанных в %FILE% ИБ                       =
ECHO = 7 - Вывести список всех фактически имеющихся в каталоге BASE ИБ             =
ECHO = 8 - Редактировать список ИБ %FILE% в текстовом редакторе              =
ECHO = 9 - Удаление %FILE% [при запуске К+ он сформируется автоматически]    =
ECHO ===============================================================================
ECHO = 0 - Вернуться назад в главное меню     [ 00 - Выход ]                       =
ECHO ===============================================================================
SET /p MENU1=Введите номер операции и нажмите клавишу ENTER: 
ECHO Выполняется операция № %MENU1%! Ожидайте...
IF "%MENU1%"=="0" GOTO start
IF "%MENU1%"=="00" EXIT
IF "%MENU1%"=="1" (
   CD BASE
   DEL /q /f %FILE%
   FOR /f "tokens=* delims=" %%a in ('dir /b /ad *.* ^| findstr /v "COMMON %el1%" ') do >>%FILE% ECHO %%~a
   CD ..
   GOTO editbl
   )
IF "%MENU1%"=="2" SET /p IB=Введите на латинице аббревиатуру имени добавляемой ИБ: 
IF "%MENU1%"=="2" (
   IF "%IB%"=="XXXXX" (
      ECHO Вы не выполнили ввод. Повторите!
      PAUSE
      GOTO editbl
      )
   CD BASE
   findstr /e /b "%IB%" "%FILE%" >nul&& ECHO String Already exist || (
   1>>"%FILE%" ECHO %IB%
   sort "%FILE%" > "%FILE%.tmp" && move "%FILE%.tmp" "%FILE%" 1>nul  2>&1) 
   CD ..
   GOTO editbl
   )
IF "%MENU1%"=="3" SET /p IB=Введите на латинице аббревиатуру имени удаляемой ИБ: 
IF "%MENU1%"=="3" (
   IF "%IB%"=="XXXXX" (
      ECHO Вы не выполнили ввод. Повторите!
      PAUSE
      GOTO editbl
      )
   CD BASE
   findstr /v /b /e "%IB%" "%FILE%">"%FILE%.tmp" && move "%FILE%.tmp" "%FILE%" 1>nul 2>&1 
   CD ..
   GOTO editbl
   )
IF "%MENU1%"=="4" (
   SET IB=DOF
   CD BASE
   findstr /e /b "%IB%" "%FILE%" >nul&& ECHO String Already exist || (
   1>>"%FILE%" ECHO %IB%
   sort "%FILE%" > "%FILE%.tmp" && move "%FILE%.tmp" "%FILE%" 1>nul  2>&1) 
   CD ..
   GOTO editbl
   )
IF "%MENU1%"=="5" (
   SET IB=DOF
   CD BASE
   findstr /v /b /e "%IB%" "%FILE%">"%FILE%.tmp" && move "%FILE%.tmp" "%FILE%" 1>nul 2>&1 
   CD ..
   GOTO editbl
   )
IF "%MENU1%"=="6" (
   CD BASE
   MODE CON COLS=80 LINES=200
   findstr /b "." "%FILE%"
   CD ..
   ECHO .....Вывод списка завершен.....
   PAUSE
   GOTO editbl
   )
IF "%MENU1%"=="7" (
   CD BASE
   MODE CON COLS=80 LINES=200
   FOR /f "tokens=* delims=" %%a in ('dir /b /ad *.* ^| findstr /v "COMMON %el1%" ') do ECHO %%~a
   CD ..
   ECHO .....Вывод списка завершен.....
   PAUSE
   GOTO editbl
   )
IF "%MENU1%"=="8" (
   %STRT1% notepad.exe BASE\BASELIST.CFG
   GOTO editbl
   )
IF "%MENU1%"=="9" (
   COLOR 2F
   DEL /s /q /f BASE\BASELIST.CFG
   GOTO editbl
   )
GOTO start


:BTR
COLOR B0
TITLE Зеркальный комплект. Транзакционное фоновое пополнение.
SET MENU1=0
MODE CON COLS=%WINDOWCOLS% LINES=%WINDOWLINES%
SET FILE=BASELIST.CFG
SET IB=XXXXX
CLS
ECHO ===============================================================================
ECHO = 1 - Преобразование обычного комплекта в зеркальный   [/ADM /CONVERT2MIRROR] =
ECHO = 2 - Преобразование зеркального комплекта в обычный   [/ADM   /CONVERT2MONO] =
ECHO = 3 - Замена ИБ или Копирование зеркального комплекта  [/ADM     /PACKMIRROR] =
ECHO = 4 - Админист-ние / Возобновление работы после Замены ИБ/Копирования  [/ADM] =
ECHO ===============================================================================
ECHO = 0 - Вернуться назад в главное меню                           [ 00 - Выход ] =
ECHO ===============================================================================
SET /p MENU1=Введите номер операции и нажмите клавишу ENTER: 
ECHO Выполняется операция № %MENU1%! Ожидайте...
IF "%MENU1%"=="0" GOTO start
IF "%MENU1%"=="00" EXIT
IF "%MENU1%"=="1" (
   %STRT1% %CONS% /ADM /CONVERT2MIRROR
   GOTO BTR
   )
IF "%MENU1%"=="2" (
   %STRT1% %CONS% /ADM /CONVERT2MONO
   GOTO BTR
   )
IF "%MENU1%"=="3" (
   %STRT1% %CONS% /ADM /PACKMIRROR
   GOTO BTR
   )
IF "%MENU1%"=="4" (
   %STRT1% %CONS% /ADM
   GOTO BTR
   )
GOTO start


:REGFLAG1
REM Обработка попытки выполнения команд на незарегистрированном комплекте программы
COLOR 0E
ECHO ===============================================================================
ECHO =         Ваш комплект программы КонсультантПлюс не зарегистрирован!          =
ECHO =  Если вы это уже исправили, закройте это окно и выполните запуск повторно.  =
ECHO =    Для выполнения этого варианта запуска/команды необходима регистрация.    =
ECHO =    Желаете выполнить автоматическую регистрацию и продолжить выполнение?    =
ECHO ===============================================================================
SET /p MENU1=Введите 1 [Да] / 0 [Нет] и нажмите клавишу ENTER: 
ECHO ===============================================================================
IF "%MENU1%"=="1" (
   ECHO Выполняется регистрация! Ожидайте...
   CALL :registr
   GOTO :eof
   )
IF /I "%MENU1%"=="Y" (
   ECHO Выполняется регистрация! Ожидайте...
   CALL :registr
   GOTO :eof
   )
IF /I "%MENU1%"=="YES" (
   ECHO Выполняется регистрация! Ожидайте...
   CALL :registr
   GOTO :eof
   )
GOTO start
GOTO :eof


:testrgt0
IF NOT EXIST RGT\*.RGT (
   COLOR CF
   ECHO ===============================================================================
   ECHO =          Внимание, в директории RGT отсутствуют CONS###.RGT файлы!          =
   ECHO =             Формирование пополнений без этих файлов невозможно!             =
   ECHO =  Сформируйте RGT в Регистрирующем Центре [РЦ] или обратитесь к специалисту  =
   ECHO ===============================================================================
   PAUSE
   GOTO start
   )
GOTO :eof


:testqst0
IF NOT EXIST RECEIVE\*.QST (
   COLOR CF
   ECHO ===============================================================================
   ECHO =    Внимание, в директории RECEIVE отсутствуют QST запросы для обработки!    =
   ECHO =       Поместите запросы на обработку и повторите формирование ответа.       =
   ECHO ===============================================================================
   PAUSE
   GOTO start
   )
GOTO :eof


:testqst1
IF EXIST RECEIVE\*.QST (
   COLOR CF
   ECHO ===============================================================================
   ECHO =     Внимание, в директории RECEIVE остались необработанные QST запросы!     =
   ECHO =          Вероятно у вас отсутствуют необходимые ИБ либо RGT файлы.          =
   ECHO ===============================================================================
   PAUSE
   )
GOTO :eof


:DATTIM
REM Определяем двумя способами время, первые 2 FOR - перезаписываются 3тим - способ 2, независим от региональных настроек
FOR /f "tokens=1-3 delims=:,./- " %%I in ("%DATE%") do SET DAT=%%K.%%J.%%I
FOR /f "tokens=1-3 delims=:,./- " %%I in ("%TIME%") do SET TIM=%%I.%%J.%%K
FOR /f "delims=." %%i in ('wmic.exe OS get LocalDateTime ^| find "."') do set sDATTIM=%%i
SET DAT=%sDATTIM:~0,4%.%sDATTIM:~4,2%.%sDATTIM:~6,2%
SET TIM=%sDATTIM:~8,2%.%sDATTIM:~10,2%.%sDATTIM:~12,2%
GOTO :eof


:WEEK
REM Определяем день недели и месяц format: dd.mm.yyyy:
SET /a y=%date:~6,4%&set /a m=1%date:~3,2%-100&set /a d=1%date:~0,2%-100
SET /a i=(%y%-1901)*365 + (%y%-1901)/4 + %d% + (!(%y% %% 4))*(!((%m%-3)^&16))
SET /a i=(%i%+(%m%-1)*30+2*(!((%m%-7)^&16))-1+((65611044^>^>(2*%m%))^&3))%%7+1
FOR /f "tokens=%i% delims=/" %%a in ('
ECHO/MON/TUE/WED/THU/FRI/SAT/SUN') do set "DayOfWeek=%%a"
FOR /f "tokens=%m% delims=/" %%a in ('
ECHO/JAN/FEB/MAR/APR/MAY/JUN/JUL/AUG/SEP/OCT/NOV/DEC/') do set "mmm=%%a"
GOTO :eof


:prop
EXIT