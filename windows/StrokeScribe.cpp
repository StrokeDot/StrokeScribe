// Real GUI host: CPython runs inside StrokeScribe.exe, never in a renamed Python binary.
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <windows.h>
#include <shellapi.h>
#include <sddl.h>
#include <cstdint>
#include <cwchar>
#include <filesystem>
#include <string>
#include <vector>
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "delayimp.lib")
#pragma comment(lib, "advapi32.lib")

static int error_box(const wchar_t* text) {
    MessageBoxW(nullptr,text,L"StrokeScribe could not start",MB_OK|MB_ICONERROR);
    return 1;
}

// Decide primary/secondary before Python imports or update recovery. The mutex
// is scoped to this installation and Windows user, and never inherited by workers.
struct InstanceGuard {
    HANDLE handle=nullptr;bool owner=false;
    ~InstanceGuard() { if (owner) ReleaseMutex(handle);if (handle) CloseHandle(handle); }
    bool acquire(const std::filesystem::path& root,bool& secondary) {
        HANDLE token=nullptr;DWORD bytes=0;
        if (!OpenProcessToken(GetCurrentProcess(),TOKEN_QUERY,&token)) return false;
        GetTokenInformation(token,TokenUser,nullptr,0,&bytes);
        std::vector<unsigned char> buffer(bytes);
        bool ok=GetTokenInformation(token,TokenUser,buffer.data(),bytes,&bytes)!=FALSE;
        CloseHandle(token);if (!ok) return false;
        LPWSTR sid=nullptr;
        if (!ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(buffer.data())->User.Sid,&sid)) return false;
        std::wstring user(sid);LocalFree(sid);
        auto location=root.lexically_normal().wstring();
        CharLowerBuffW(location.data(),DWORD(location.size()));
        uint64_t hash=14695981039346656037ull;
        for (wchar_t c:location) { hash^=uint16_t(c);hash*=1099511628211ull; }
        std::wstring name=L"Local\\StrokeScribe."+user+L"."+std::to_wstring(hash);
        std::wstring acl=L"D:P(A;;GA;;;"+user+L")";
        PSECURITY_DESCRIPTOR descriptor=nullptr;
        if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(acl.c_str(),SDDL_REVISION_1,&descriptor,nullptr)) return false;
        SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES),descriptor,FALSE};
        handle=CreateMutexW(&security,FALSE,name.c_str());
        LocalFree(descriptor);
        if (!handle) return false;
        DWORD acquired=WaitForSingleObject(handle,0);
        owner=acquired==WAIT_OBJECT_0 || acquired==WAIT_ABANDONED;
        secondary=!owner;
        return owner || acquired==WAIT_TIMEOUT;
    }
};

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
    InstanceGuard instance;bool secondary=false;
    if (!instance.acquire(root,secondary)) {LocalFree(args);return error_box(L"Cannot establish the current user's application identity.");}
    SetEnvironmentVariableW(L"STROKESCRIBE_SECONDARY_LAUNCH",secondary?L"1":L"0");
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
    PyStatus status=PyConfig_SetString(&config,&config.program_name,program.c_str());
    auto check=[&](PyStatus next){if (!PyStatus_Exception(status)) status=next;};
    check(PyConfig_SetString(&config,&config.executable,program.c_str()));
    check(PyConfig_SetString(&config,&config.home,runtime.c_str()));
    check(PyConfig_SetString(&config,&config.run_filename,script.c_str()));
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
