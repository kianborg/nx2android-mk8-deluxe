// Optional per-app Vulkan driver selection. System Vulkan remains the default.
#include "gfx_vk.h"
#include <dlfcn.h>
#include <string.h>
#include <ctype.h>

typedef void *(*open_custom_t)(int,int,const char *,const char *,const char *,const char *,const char *,void **);
static int driver_basename(const char *name) {
    size_t n=strlen(name);if (n<7 || n>200 || strncmp(name,"lib",3) || strcmp(name+n-3,".so") || strstr(name,"..")) return 0;
    for (const char *p=name;*p;p++) if (!isalnum((unsigned char)*p) && *p!='_' && *p!='-' && *p!='.') return 0;
    return 1;
}
void *vk_open_loader(void) {
    const char *choice=getenv("DM_VK_DRIVER");
    if (!choice || !*choice || !strcmp(choice,"system")) {
        void *lib=dlopen("libvulkan.so",RTLD_NOW|RTLD_LOCAL);
        if (!lib) die("[vk] system Vulkan loader: %s",dlerror());
        VKLOG("Vulkan loader: system");return lib;
    }
    const char *name=!strcmp(choice,"turnip")?"libnx2a_turnip.so":choice;
    if (!driver_basename(name)) die("[vk] invalid custom Vulkan library basename");
    // APK extractNativeLibs=true supplies the read-only native library directory,
    // as required for AdrenoTools hooks and Android's native-code loading rules.
    Dl_info info;if (!dladdr((void *)&vk_open_loader,&info) || !info.dli_fname) die("[vk] cannot locate the APK's native libraries");
    char directory[1024];if (strlen(info.dli_fname)>=sizeof directory) die("[vk] native library path is too long");
    strcpy(directory,info.dli_fname);char *slash=strrchr(directory,'/');if (!slash) die("[vk] native library directory unavailable");slash[1]=0;
    char path[1300];snprintf(path,sizeof path,"%slibadrenotools.so",directory);
    void *helper=dlopen(path,RTLD_NOW|RTLD_LOCAL);
    if (!helper) die("[vk] custom driver helper unavailable: rebuild with --vulkan-driver ZIP (%s)",dlerror());
    open_custom_t open_custom=(open_custom_t)dlsym(helper,"adrenotools_open_libvulkan");
    if (!open_custom) die("[vk] AdrenoTools entry point unavailable");
    void *lib=open_custom(RTLD_NOW|RTLD_LOCAL,1,NULL,directory,directory,name,NULL,NULL);
    if (!lib) die("[vk] custom Vulkan driver %s could not load; set DM_VK_DRIVER=system to restore system Vulkan",name);
    if (!dlsym(lib,"vkGetInstanceProcAddr")) die("[vk] custom driver loader has no vkGetInstanceProcAddr");
    VKLOG("Vulkan loader: AdrenoTools custom driver requested %s (native directory %s); verify GPU/driver properties below",name,directory);
    return lib;
}
