// Real GUI host: CPython runs inside StrokeScribe.exe, never in a renamed Python binary.
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <windows.h>
#include <shellapi.h>
#include <filesystem>
#include <string>
#include <vector>
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "delayimp.lib")

static int error_box(const wchar_t* text) {
    MessageBoxW(nullptr,text,L"StrokeScribe could not start",MB_OK|MB_ICONERROR);
    return 1;
}
int WINAPI wWinMain(HINSTANCE,HINSTANCE,PWSTR,int) {
    std::vector<wchar_t> filename(32768);
    DWORD length=GetModuleFileNameW(nullptr,filename.data(),DWORD(filename.size()));
    if (!length || length>=filename.size()) return error_box(L"Cannot locate the installed application.");
    std::filesystem::path executable(filename.data()),root=executable.parent_path(),runtime=root/L"runtime";
    int argc=0;wchar_t** args=CommandLineToArgvW(GetCommandLineW(),&argc);
    if (!args) return error_box(L"Cannot read the Windows launch arguments.");
    int first=1;
    if (argc>1 && std::wstring(args[1])==L"--restart-wait") {
        if (argc!=3) { LocalFree(args);return error_box(L"Invalid restart request."); }
        wchar_t* end=nullptr;unsigned long pid=wcstoul(args[2],&end,10);
        if (!pid || !end || *end || pid==GetCurrentProcessId()) {LocalFree(args);return error_box(L"Invalid restart process.");}
        HANDLE previous=OpenProcess(SYNCHRONIZE|PROCESS_QUERY_LIMITED_INFORMATION,FALSE,DWORD(pid));
        if (previous) {
            std::vector<wchar_t> previous_name(32768);DWORD size=DWORD(previous_name.size());
            bool same=QueryFullProcessImageNameW(previous,0,previous_name.data(),&size)
                && _wcsicmp(previous_name.data(),executable.c_str())==0;
            if (!same || WaitForSingleObject(previous,30000)!=WAIT_OBJECT_0) {
                CloseHandle(previous);LocalFree(args);
                return error_box(L"The previous StrokeScribe is still closing. Please try again.");
            }
            CloseHandle(previous);
        } else if (GetLastError()!=ERROR_INVALID_PARAMETER) {
            LocalFree(args);return error_box(L"Cannot verify that the previous application closed.");
        }
        first=argc;
    }
    // Delay-load prevents Windows searching for the runtime DLL before this
    // secure full-path load. Existing worker launches still use pythonw.exe.
    SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    AddDllDirectory(runtime.c_str());
    auto dll=runtime/L"python312.dll";
    if (!LoadLibraryExW(dll.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)) {
        LocalFree(args);return error_box(L"The private Python runtime is missing. Reinstall StrokeScribe using its full installer.");
    }
    SetEnvironmentVariableW(L"STROKESCRIBE_NATIVE_HOST",L"1");
    std::wstring program=(runtime/L"pythonw.exe").wstring(),script=(root/L"startup.py").wstring();
    std::vector<std::wstring> values{script};
    for (int i=first;i<argc;++i) values.emplace_back(args[i]);
    LocalFree(args);
    std::vector<wchar_t*> argv;for (auto& value:values) argv.push_back(value.data());
    PyConfig config;PyConfig_InitPythonConfig(&config);
    config.isolated=1;config.parse_argv=0;config.module_search_paths_set=1;
    PyStatus status=PyConfig_SetString(&config.program_name,program.c_str());
    auto check=[&](PyStatus next){if (!PyStatus_Exception(status)) status=next;};
    check(PyConfig_SetString(&config.executable,program.c_str()));
    check(PyConfig_SetString(&config.home,runtime.c_str()));
    check(PyConfig_SetString(&config.run_filename,script.c_str()));
    check(PyConfig_SetArgv(&config,int(argv.size()),argv.data()));
    for (const auto& path:{root,runtime/L"python312.zip",runtime/L"DLLs",runtime/L"Lib",runtime/L"Lib"/L"site-packages"})
        check(PyWideStringList_Append(&config.module_search_paths,path.c_str()));
    if (!PyStatus_Exception(status)) status=Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) {
        bool exiting=PyStatus_IsExit(status);int code=status.exitcode;
        PyConfig_Clear(&config);
        return exiting?code:error_box(L"The installed Python runtime could not initialize. Reinstall StrokeScribe.");
    }
    PyConfig_Clear(&config);
    return Py_RunMain();
}
