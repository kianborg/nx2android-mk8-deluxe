// Opt-in, bounded CPU replay snapshot of one indexed draw; not a GPU readback.
// Included after replay state is declared. The packet is for offline vertex analysis.
#pragma once
static int packet_blob(const char *root, const char *name, uint64_t address, uint64_t size, int shadow) {
    if (!address || !size || size > 1024*1024 || !vk_pool_of(address,size)) return 0;
    char path[1200];snprintf(path,sizeof path,"%s/%s",root,name);FILE *f=fopen(path,"wb");if (!f) return 0;
    uint8_t bytes[4096];int ok=1;
    for (uint64_t off=0;off<size;) {
        size_t n=size-off>sizeof bytes?sizeof bytes:(size_t)(size-off);
        if (shadow) vk_ubd_read(address+off,n,bytes); else memcpy(bytes,(const void *)(uintptr_t)(address+off),n);
        if (fwrite(bytes,1,n,f)!=n) {ok=0;break;} off+=n;
    }
    if (fclose(f)) ok=0;
    return ok;
}
static void draw_packet(const p_draw_idx *d) {
    static int done;static uint64_t requested;static int init;
    if (!init) {const char *e=getenv("DM_VK_DRAW_PACKET");requested=e?strtoull(e,NULL,16):0;init=1;}
    if (!requested || done || !S.sh[0] || S.sh[0]->key!=requested || S.rast_discard || !S.rt_has_col[0] || !S.sh[1] || d->ind || d->count<=0 || d->itype<0 || d->itype>2) return;
    done=1;const char *root=getenv("DM_ROOT");if (!root) root=".";
    char path[1200];snprintf(path,sizeof path,"%s/draw_packet.json",root);FILE *f=fopen(path,"wb");
    if (!f) {VKLOG("[RED] draw packet: cannot open manifest");return;}
    int ok=1;uint32_t used=0,mask=S.sh[0]->local[0];
    fprintf(f,"{\"version\":1,\"view\":\"CPU replay (not GPU readback)\",\"present\":%llu,\"vertex_shader\":\"%016llx\",\"fragment_shader\":\"%016llx\",\"primitive\":%d,\"index_type\":%d,\"count\":%d,\"base_vertex\":%d,\"instances\":%d,\"attributes\":[",(unsigned long long)g_tex_frame,(unsigned long long)S.sh[0]->key,(unsigned long long)S.sh[1]->key,d->prim,d->itype,d->count,d->base_vertex,d->instances);
    int comma=0;
    for (int l=0;l<16;l++) if (mask>>l&1) {
        va_st a;memcpy(&a,&S.vattr[l],4);if (a.stream<16) used|=1u<<a.stream;else ok=0;
        fprintf(f,"%s{\"location\":%d,\"format\":%u,\"stream\":%u,\"offset\":%u}",comma?",":"",l,a.fmt,a.stream,a.offset);comma=1;
    }
    fprintf(f,"],\"streams\":[");comma=0;
    for (int b=0;b<16;b++) if (used>>b&1) {
        char name[80];snprintf(name,sizeof name,"draw_packet_stream_%02d.bin",b);
        int saved=packet_blob(root,name,S.vbuf[b].address,S.vbuf[b].size,0);ok&=saved;
        fprintf(f,"%s{\"stream\":%d,\"stride\":%u,\"divisor\":%u,\"size\":%llu,\"saved\":%s,\"file\":\"%s\"}",comma?",":"",b,S.vstream[b].stride,S.vstream[b].divisor,(unsigned long long)S.vbuf[b].size,saved?"true":"false",name);comma=1;
    }
    uint64_t index_size=(uint64_t)d->count*(d->itype==0?1:d->itype==1?2:4);
    int saved=packet_blob(root,"draw_packet_indices.bin",d->ibuf,index_size,0);ok&=saved;
    fprintf(f,"],\"indices_saved\":%s,\"uniforms\":[",saved?"true":"false");comma=0;
    vkshader_t *vs=S.sh[0];
    for (int i=0;i<vs->nbind;i++) {
        const dmsv_bind *b=&vs->b[i];if (b->kind!=RK_CBUF || b->reg<0 || b->reg>=16) continue;
        uint64_t address=S.ubo[0][b->reg].addr,size=S.ubo[0][b->reg].size;
        char name[80];snprintf(name,sizeof name,"draw_packet_uniform_%02d.bin",b->reg);
        saved=packet_blob(root,name,address,size,1);ok&=saved;
        fprintf(f,"%s{\"binding\":%u,\"register\":%d,\"size\":%llu,\"saved\":%s,\"file\":\"%s\"}",comma?",":"",b->binding,b->reg,(unsigned long long)size,saved?"true":"false",name);comma=1;
    }
    fprintf(f,"],\"complete\":%s}\n",ok?"true":"false");if (fclose(f)) ok=0;
    VKLOG("%sdraw packet: shader %016llx, present %llu, %d indices; %s/draw_packet.json (CPU replay data)",ok?"":"[RED] ",(unsigned long long)requested,(unsigned long long)g_tex_frame,d->count,root);
}
