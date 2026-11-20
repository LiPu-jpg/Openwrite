/** Load only the editor resources shipped and served by this plugin. */
declare const resources: {
    readonly Lute: "/studio-panel/vendor/vditor/dist/js/lute/lute.min.js";
    readonly VditorI18n: "/studio-panel/vendor/vditor/dist/js/i18n/zh_CN.js";
};
type GlobalName = keyof typeof resources;
export declare function loadPackagedEditorGlobal(name: GlobalName): Promise<void>;
export {};
