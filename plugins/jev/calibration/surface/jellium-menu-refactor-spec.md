# Surface Spec: Rust
The set of `fn`, `struct`, `enum`, `trait`, and `impl`
declarations the resulting combined diff adds must equal the declarations
under `## Additions`, and the set it deletes must equal the declarations
under `## Deletions`.

## Additions

### src/jfn_cef/src/app.rs
```rust
struct PopupOptions {
    options: Vec<String>,
    selected: Option<usize>,
    selectable: Vec<i32>,
    anchor: Option<(i32, i32)>,
}
```

### src/jfn_cef/src/business_web.rs
```rust
pub(crate) fn install(client: &Arc<Inner>);

fn handle_message(app: &jfn_platform_abi::App, message: BrowserMessage) -> bool;
```

### src/jfn_cef/src/client/popup.rs
```rust
impl Inner {
    pub(crate) fn set_popup_options(
        self: &Arc<Self>,
        opts: Vec<String>,
        selected: Option<usize>,
        selectable: Vec<i32>,
        anchor: Option<(i32, i32)>,
    );
}
```

### src/jfn_cef/src/client.rs
```rust
pub(crate) struct Inner {
    pub(crate) session: Arc<crate::runtime::Session>,
    name: Mutex<String>,
    _owner_connected: Sender<Infallible>,
    owner_disconnected: Receiver<Infallible>,
    painting: Mutex<Painting>,
    browser: Mutex<BrowserState>,
    surface: Arc<WebOverlaySurface>,
    width: AtomicI32,
    height: AtomicI32,
    scale: AtomicCell<Option<jfn_platform_abi::Scale>>,
    pub(super) paint_mode: PaintMode,
    paint_scheduler: PaintScheduler,
    pub(crate) frame_rate: AtomicCell<Option<FrameRate>>,
    resize_scheduled: AtomicBool,
    last_was_resized_ns: AtomicI64,
    popup: Mutex<PopupState>,
    deferred_navigation: Arc<DeferredNavigation>,
    message_handler: Mutex<Option<Box<MessageFn>>>,
    created_callback: Mutex<Option<Arc<CreatedFn>>>,
    pub(crate) app: Arc<jfn_platform_abi::App>,
    pub(crate) channel: crate::receiver::Channel,
    pub(crate) menu: Mutex<Menu>,
}

fn menu_label(command_id: c_int) -> Option<ContextMenuLabel>;

pub(crate) struct Menu {
    showing: Option<MenuSerial>,
    app: Arc<jfn_platform_abi::App>,
}

impl Menu {
    pub(crate) fn open_context_menu(
        &mut self,
        callback: RunContextMenuCallback,
        model: &MenuModel,
        anchor: LogicalPoint,
        sender: std::sync::mpsc::Sender<CefMsg>,
    );
    pub(crate) fn open_dropdown(&mut self, builder: MenuBuilder);
    pub(crate) fn finish(&mut self, message: CefMsg);
}

#[derive(Default)]
struct PopupState {
    x: i32,
    y: i32,
    w: i32,
    h: i32,
    visible: bool,
    options: Vec<String>,
    selected_idx: Option<usize>,
    selectable: Vec<i32>,
    anchor: Option<(i32, i32)>,
    size_received: bool,
    options_received: bool,
}

impl Inner {
    pub(crate) fn new(
        session: Arc<crate::runtime::Session>,
        surface: Arc<WebOverlaySurface>,
        deferred_navigation: Arc<DeferredNavigation>,
        paint_mode: PaintMode,
        frame_rate: Option<FrameRate>,
        app: Arc<jfn_platform_abi::App>,
    ) -> Arc<Self>;
}
```

### src/jfn_cef/src/receiver.rs
```rust
pub(crate) enum CefMsg {
    Menu { serial: MenuSerial, callback: Box<dyn FnOnce() + Send> },
}

pub(crate) struct Channel {
    sender: std::sync::mpsc::Sender<CefMsg>,
    _thread: JoinHandle<()>,
}

impl Channel {
    pub(crate) fn new(inner: Weak<Inner>) -> Channel;
    pub(crate) fn sender(&self) -> std::sync::mpsc::Sender<CefMsg>;
}
```

### src/jfn_cef/src/runtime.rs
```rust
pub struct InitOptions {
    pub log_severity: LogSeverity,
    pub remote_debugging_port: DebuggingPort,
    pub disable_gpu_compositing: bool,
    pub locale: String,
}
```

### src/jfn_cef/src/web_overlay.rs
```rust
pub struct WebOverlayConfig {
    pub on_event: crate::WebEventHandler,
    pub app: Arc<jfn_platform_abi::App>,
    pub frame_rate: Option<RefreshRate>,
    pub shared_textures: bool,
}

struct Overlay {
    app: Arc<jfn_platform_abi::App>,
    session: Arc<crate::runtime::Session>,
    platform: Mutex<Option<jfn_platform_abi::PlatformLease>>,
    subscription: Mutex<Option<jfn_input::ShellStateSubscription>>,
    close: Mutex<()>,
    window_subscription: Mutex<Option<jfn_platform_abi::WindowSubscription>>,
    client: OnceLock<Weak<Inner>>,
    deferred_navigation: Arc<DeferredNavigation>,
    paint_mode: PaintMode,
    frame_rate: AtomicCell<Option<FrameRate>>,
}
```

### src/jfn_rust/src/app.rs
```rust
fn initialize_cef(
    runtime: BrowserCef,
    platform: &jfn_platform_abi::PlatformRuntime,
    opts: &StartupOptions,
    app: &App,
) -> Result<CefInit, jfn_cef::InitError>;

impl StartupResources<MpvNative> {
    fn initialize(
        mut self,
        app: Arc<App>,
    ) -> Result<
        StartupResources<InitializedNative>,
        jfn_platform_abi::PlatformInitError,
    >;
}

fn start_web_overlay(
    rate: Option<jfn_gpu_paint::RefreshRate>,
    cef: &CefInit,
    user_video_bg: u32,
    app: Arc<App>,
) -> Result<StartedOverlay, OverlayStartupError>;

fn run_app(
    instance: &Instance,
    opts: StartupOptions,
    runtime: BrowserCef,
    metadata: ApplicationMetadata,
    locale: jfn_platform_abi::lang::LanguageLoader,
) -> c_int;

fn run_with_cef(
    boot: ReadyBoot,
    deferred: Option<BrowserCef>,
    mut resources: StartupResources<InitializedNative>,
    opts: &StartupOptions,
    instance: &Instance,
    app: Arc<App>,
) -> c_int;
```

### src/jfn_rust/src/app_menu.rs
```rust
pub(crate) struct MenuManager {
    next_serial: AtomicUsize,
    showing: Mutex<Option<MenuSerial>>,
}

impl MenuManager {
    pub(crate) fn new() -> MenuManager;
    pub(crate) fn next_serial(&self) -> MenuSerial;
    pub(crate) fn open(&self, serial: MenuSerial, builder: MenuBuilder);
    pub(crate) fn close(&self, serial: MenuSerial);
}
```

### src/jfn_rust/src/shell/actor.rs
```rust
pub enum Work {
    Event(Event),
    Resize { extent: WindowExtent },
    Redraw,
    OpenAbout,
    OpenClientSettings,
    Chrome(ChromeInputs),
    ChromeBackground(iced_core::Color),
    SelectionText { reader: Reader, text: Option<String> },
    ContextMenu(LogicalPoint),
    EditMenuAtCaret,
    PrimaryPaste(LogicalPoint),
    EditAt { field: Target, command: jfn_input::EditCommand },
    WebAttached(jfn_cef::WebOverlay),
    WebEvent(jfn_cef::WebEvent),
    OpenContextMenu(MenuSerial, ContextMenuBuilder),
    OpenDropdown(MenuSerial, MenuBuilder),
    CloseMenu(MenuSerial),
    ToggleFullscreen,
    Exit,
    Shutdown,
}

impl From<AppMsg> for Work;

impl Channel {
    pub(super) fn sender(&self) -> Sender<Work>;
}

impl Actor {
    pub(crate) fn spawn(
        surface: SurfaceHandle,
        channel: &Channel,
        metadata: crate::shell::metadata::ApplicationMetadata,
        app: Arc<App>,
        menu: Arc<MenuManager>,
        platform: jfn_platform_abi::PlatformLease,
        on_ready: std::sync::mpsc::SyncSender<Result<(), LoopStartError>>,
    ) -> Result<Actor, crate::shell::StartError>;
}

impl Model {
    fn view(&self, app: &App) -> Element<'_, Message, Theme, iced_wgpu::Renderer>;
}

struct Loop {
    app: Arc<App>,
    menu: Arc<MenuManager>,
    surface: SurfaceHandle,
    wake_tx: Sender<Work>,
    painter: Painter,
    model: Model,
    cache: user_interface::Cache,
    events: Vec<Event>,
    cursor: Cursor,
    waker: shell::Waker,
    redraw: Redraw,
    current: WindowExtent,
    focus: FocusMemory,
    pending: Deadline,
    immediate: bool,
    batch: Vec<Work>,
    queued: Vec<Apply>,
    deferred: Vec<Deferred>,
    last_primary: Option<(Id, u64)>,
    drew_nothing_yet: bool,
}

fn run(
    surface: SurfaceHandle,
    rx: &Receiver<Work>,
    wake_tx: &Sender<Work>,
    metadata: crate::shell::metadata::ApplicationMetadata,
    app: Arc<App>,
    menu: Arc<MenuManager>,
    on_ready: std::sync::mpsc::SyncSender<Result<(), LoopStartError>>,
);

impl Loop {
    fn start(
        surface: SurfaceHandle,
        wake_tx: &Sender<Work>,
        target: jfn_gpu_paint::WindowTarget,
        metadata: crate::shell::metadata::ApplicationMetadata,
        app: Arc<App>,
        menu: Arc<MenuManager>,
    ) -> Result<Loop, LoopStartError>;
}

fn resolve_deferred(
    ui: &mut Ui<'_>,
    painter: &mut Painter,
    deferred: &mut Vec<Deferred>,
    queued: &mut Vec<Apply>,
    wake_tx: &Sender<Work>,
    app: &App,
);

fn raise_menu(
    fields: &Fields,
    p: LogicalPoint,
    queued: &mut Vec<Apply>,
    app: &App,
) -> Option<LogicalPoint>;
```

### src/jfn_rust/src/shell/connect.rs
```rust
impl Connect {
    pub fn view<'a>(
        &'a self,
        screen: &'a Screen,
        locale: &LanguageLoader,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn form_view<'a>(
        &'a self,
        url: &'a str,
        locale: &LanguageLoader,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn failure_view(
        &self,
        locale: &LanguageLoader,
    ) -> Element<'_, Message, Theme, iced_wgpu::Renderer>;
}
```

### src/jfn_rust/src/shell/field.rs
```rust
pub struct Field<'a, Message> {
    id: Id,
    placeholder: Cow<'a, str>,
    value: &'a str,
    on_input: Option<Box<dyn Fn(String) -> Message + 'a>>,
    on_submit: Option<Message>,
    on_unfocus: Option<Message>,
    padding: Padding,
    size: Option<Pixels>,
    width: Length,
}

pub fn field<'a, Message>(
    id: Id,
    placeholder: impl Into<Cow<'a, str>>,
    value: &'a str,
) -> Field<'a, Message>;

impl<'a, Message: Clone + 'a> Field<'a, Message> {
    fn placeholder_text(&self, renderer: &Renderer, bounds: Size) -> Text<&str, Font>;
}
```

### src/jfn_rust/src/shell/menu.rs
```rust
impl Item {
    pub fn label(self) -> ContextMenuLabel;
}

pub fn open_edit(app: &App, field: &Snapshot, anchor: LogicalPoint);
```

### src/jfn_rust/src/shell/mod.rs
```rust
pub(crate) fn shell_start(
    platform: &jfn_platform_abi::PlatformRuntime,
    metadata: metadata::ApplicationMetadata,
    app: Arc<App>,
    menu: Arc<MenuManager>,
) -> Result<(Shell, Readiness), StartError>;

pub fn shell_sender() -> std::sync::mpsc::Sender<Work>;
```

### src/jfn_rust/src/shell/modal.rs
```rust
impl Stack {
    pub fn view<'a>(
        &'a self,
        screen: &'a Screen,
        locale: &LanguageLoader,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
}
```

### src/jfn_rust/src/shell/settings.rs
```rust
impl Settings {
    pub fn view(
        &self,
        locale: &LanguageLoader,
    ) -> Element<'_, Message, Theme, iced_wgpu::Renderer>;
    fn group<'a>(
        &self,
        title: String,
        controls: iced_widget::Column<'a, Message, Theme, iced_wgpu::Renderer>,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn setting<'a>(
        &self,
        label: String,
        control: Element<'a, Message, Theme, iced_wgpu::Renderer>,
        help: String,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn selection<'a>(
        &self,
        label: String,
        control: Element<'a, Message, Theme, iced_wgpu::Renderer>,
        help: String,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn toggle<'a>(
        &self,
        id: Id,
        label: String,
        value: bool,
        changed: fn(bool) -> Message,
        help: String,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn action<'a>(
        &self,
        id: Id,
        label: String,
        message: Message,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
}

fn audio_channel_label(locale: &LanguageLoader, value: &str) -> String;

fn log_level_label(locale: &LanguageLoader, value: &str) -> String;

fn decoration_label(
    locale: &LanguageLoader,
    value: &Option<WindowDecorations>,
) -> String;

fn en() -> LanguageLoader;
```

### src/jfn_rust/src/shell/settings_overlay.rs
```rust
impl SettingsOverlay {
    pub fn view(
        &self,
        locale: &LanguageLoader,
    ) -> Element<'_, Message, Theme, iced_wgpu::Renderer>;
}
```

### src/linux_util/src/menu/engine.rs
```rust
struct Resolve {
    request: MenuRequest,
    row: Option<usize>,
}

impl Resolve {
    fn dismissed(request: MenuRequest) -> Resolve;
}

struct Menu {
    items: Arc<Vec<Vec<Item>>>,
    fsm: FsmState,
    laid: Option<Laid>,
    width: c_int,
    request: Option<MenuRequest>,
    anchor: LogicalPoint,
}

enum Job {
    Shape { generation: Generation, items: Arc<Vec<Vec<Item>>>, width: i32 },
    Paint {
        generation: Generation,
        items: Arc<Vec<Vec<Item>>>,
        layout: Arc<Layout>,
        active: i32,
    },
}

fn clear_menu(state: &mut MenuState) -> Option<MenuRequest>;

fn request_row(
    items: Vec<Item>,
    initial: Option<usize>,
) -> (MenuRequest, Receiver<c_int>);

fn request(items: Vec<Item>) -> (MenuRequest, Receiver<c_int>);

fn selectable_item() -> Item;
```

### src/linux_util/src/menu/interaction_fsm.rs
```rust
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum MenuEffect {
    Redraw,
    Close(Option<usize>),
}

pub fn step(
    s: &mut MenuState,
    ev: &MenuEvent,
    layout: Option<&Layout>,
    groups: &[Vec<Item>],
) -> Vec<MenuEffect>;

fn selectable(groups: &[Vec<Item>], active: i32) -> Option<usize>;

fn item(id: i32) -> Item;

fn disabled(id: i32) -> Item;

fn fixture() -> (Vec<Vec<Item>>, Layout);

#[test]
fn motion_onto_group_line_clears();

#[test]
fn press_on_group_line_ignored();
```

### src/linux_util/src/menu/render.rs
```rust
#[derive(Clone)]
pub struct Row {
    pub item: usize,
    pub y: i32,
    pub h: i32,
    pub enabled: bool,
}

#[derive(Clone)]
pub struct Layout {
    pub width: i32,
    pub height: i32,
    pub rows: Vec<Row>,
    pub lines: Vec<i32>,
    pub selectable: Vec<usize>,
    scale: Scale,
}

pub fn layout(fonts: &mut Fonts, groups: &[Vec<Item>], scale: Scale) -> Option<Layout>;

pub fn paint(
    fonts: &mut Fonts,
    layout: &Layout,
    groups: &[Vec<Item>],
    active: i32,
) -> Option<Pixmap>;
```

### src/macos/src/init.rs
```rust
struct AppMenuIvars {
    app: std::sync::Arc<jfn_platform_abi::App>,
}

pub fn macos_init(
    _mpv: *mut c_void,
    app: std::sync::Arc<jfn_platform_abi::App>,
) -> Result<(), jfn_platform_abi::PlatformInitError>;

unsafe fn install_main_menu(
    state: &mut InitState,
    app: std::sync::Arc<jfn_platform_abi::App>,
);
```

### src/macos/src/ns_menu.rs
```rust
pub(crate) struct MenuEntry {
    pub title: String,
    pub tag: c_int,
    pub enabled: bool,
    pub checked: bool,
}

pub(crate) struct MenuSpec {
    pub groups: Vec<Vec<MenuEntry>>,
    pub x: c_int,
    pub y: c_int,
    pub positioning_tag: Option<c_int>,
    pub min_width: Option<c_int>,
}

struct SelectionCb {
    fired: Mutex<Option<MenuRequest>>,
}

pub(crate) fn present_on_main(spec: MenuSpec, request: MenuRequest);
```

### src/platform_abi/src/app.rs
```rust
#[derive(Copy, Clone, PartialEq, Eq, Debug)]
pub struct MenuSerial(usize);

impl MenuSerial {
    pub fn new(value: usize) -> MenuSerial;
}

pub enum AppMsg {
    OpenContextMenu(MenuSerial, ContextMenuBuilder),
    OpenDropdown(MenuSerial, MenuBuilder),
    CloseMenu(MenuSerial),
    OpenClientSettings,
    OpenAbout,
}

pub struct App {
    channel: Box<dyn Fn(AppMsg) + Send + Sync>,
    next_serial: Box<dyn Fn() -> MenuSerial + Send + Sync>,
    locale: LanguageLoader,
}

impl App {
    pub fn new<T: From<AppMsg> + Send + 'static>(
        channel: std::sync::mpsc::Sender<T>,
        next_serial: impl Fn() -> MenuSerial + Send + Sync + 'static,
        locale: LanguageLoader,
    ) -> App;
    pub fn locale(&self) -> &LanguageLoader;
    pub fn new_menu(&self, anchor: LogicalPoint) -> MenuBuilder;
    pub fn new_context_menu(&self, anchor: LogicalPoint) -> ContextMenuBuilder;
    pub fn open_context_menu(&self, builder: ContextMenuBuilder);
    pub fn open_dropdown(&self, builder: MenuBuilder);
    pub fn close_menu(&self, serial: MenuSerial);
    pub fn open_client_settings(&self);
    pub fn open_about(&self);
}
```

### src/platform_abi/src/context_menu.rs
```rust
pub struct ChannelValue {
    send: Box<dyn Fn() + Send + Sync>,
}

impl ChannelValue {
    pub fn new<T: Send + 'static>(
        sender: std::sync::mpsc::Sender<T>,
        value: T,
    ) -> ChannelValue;
    pub(crate) fn send(&self);
}

pub struct Item {
    pub label: String,
    pub enabled: bool,
    pub value: ChannelValue,
}

pub struct MenuBuilder {
    pub(crate) serial: MenuSerial,
    pub(crate) anchor: LogicalPoint,
    pub(crate) items: Vec<Vec<Item>>,
    pub(crate) on_closed: Vec<ChannelValue>,
    pub(crate) current: Option<usize>,
    pub(crate) width: Option<NonZeroU32>,
}

impl MenuBuilder {
    pub fn serial(&self) -> MenuSerial;
    #[must_use]
    pub fn current(mut self, row: Option<usize>) -> MenuBuilder;
    #[must_use]
    pub fn width(mut self, width: Option<NonZeroU32>) -> MenuBuilder;
    #[must_use]
    pub fn add_items(mut self, items: Vec<Item>) -> MenuBuilder;
    #[must_use]
    pub fn add_on_closed(mut self, value: ChannelValue) -> MenuBuilder;
}

pub struct ContextMenuBuilder {
    menu: MenuBuilder,
    locale: LanguageLoader,
    items: BTreeMap<ContextMenuLabel, Item>,
}

impl ContextMenuBuilder {
    pub(crate) fn new(menu: MenuBuilder, locale: LanguageLoader) -> ContextMenuBuilder;
    pub fn serial(&self) -> MenuSerial;
    #[must_use]
    pub fn add(
        mut self,
        label: ContextMenuLabel,
        enabled: bool,
        value: ChannelValue,
    ) -> ContextMenuBuilder;
    #[must_use]
    pub fn add_on_closed(mut self, value: ChannelValue) -> ContextMenuBuilder;
}

impl From<ContextMenuBuilder> for MenuBuilder;
```

### src/platform_abi/src/lang.rs
```rust
#[derive(RustEmbed)]
#[folder = "i18n"]
struct Localizations;

#[derive(Copy, Clone, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub enum ContextMenuLabel {
    Back,
    Forward,
    Reload,
    Undo,
    Redo,
    Cut,
    Copy,
    Paste,
    SelectAll,
    Fullscreen,
    Settings,
    Exit,
}

#[derive(Copy, Clone, PartialEq, Eq, Debug)]
pub enum Label {
    ServerHost,
    ServerHostHelp,
    Submit,
    Failure,
    UnableToConnect,
    GotIt,
}

#[derive(Copy, Clone, PartialEq, Eq, Debug)]
pub enum SettingsLabel {
    Title,
    About,
    RestartNotice,
    Playback,
    Audio,
    Transcode,
    Advanced,
    MpvConfig,
    Server,
    HardwareDecoding,
    HardwareDecodingHelp,
    AudioPassthrough,
    AudioPassthroughHelp,
    ExclusiveAudio,
    ExclusiveAudioHelp,
    ChannelLayout,
    ChannelLayoutHelp,
    ChannelLayoutAuto,
    ChannelLayoutStereo,
    ChannelLayoutSurround51,
    ChannelLayoutSurround71,
    ForceTranscoding,
    ForceTranscodingHelp,
    WindowDecorations,
    WindowDecorationsHelp,
    WindowDecorationsAuto,
    WindowDecorationsCsd,
    WindowDecorationsServer,
    WindowDecorationsServerThemed,
    TransparentTitlebar,
    TransparentTitlebarHelp,
    HideScrollbar,
    HideScrollbarHelp,
    DeviceName,
    DeviceNameHelp,
    LogLevel,
    LogLevelHelp,
    LogLevelDefault,
    LogLevelVerbose,
    LogLevelDebug,
    LogLevelWarn,
    LogLevelError,
    OpenMpvConfig,
    ResetServer,
}

pub fn detect() -> Result<LanguageLoader, I18nEmbedError>;

#[derive(Clone)]
pub struct LanguageLoader(Arc<FluentLanguageLoader>);

impl LanguageLoader {
    pub fn new(
        requested: &[LanguageIdentifier],
    ) -> Result<LanguageLoader, I18nEmbedError>;
    pub fn language(&self) -> LanguageIdentifier;
    pub fn menu_label(&self, label: ContextMenuLabel) -> String;
    pub fn label(&self, label: Label) -> String;
    pub fn settings_label(&self, label: SettingsLabel) -> String;
}
```

### src/platform_abi/src/lib.rs
```rust
pub trait Platform: Send + Sync {
    fn display(&self) -> DisplayBackend;
    fn default_window_decorations(&self) -> WindowDecorations;
    fn window_decoration_options(&self) -> DecorationOptions;
    fn resolve_window_decorations(
        &self,
        configured: Option<WindowDecorations>,
    ) -> WindowDecorations;
    fn early_init(&self);
    fn init(
        &self,
        access: &LifecycleAccess,
        mpv: *mut c_void,
        app: std::sync::Arc<App>,
    ) -> Result<(), PlatformInitError>;
    fn cleanup(&self, access: &LifecycleAccess);
    fn post_window_cleanup(&self, access: &LifecycleAccess);
    fn alloc_surface(&self, initial: Visibility) -> SurfaceHandle;
    fn free_surface(&self, s: SurfaceHandle);
    fn surface_present<'a>(
        &self,
        s: SurfaceHandle,
        frame: PaintFrame<'a>,
    ) -> Result<Presented, PaintFrame<'a>>;
    fn surface_resize(&self, s: SurfaceHandle, size: SurfaceSize);
    fn surface_window_target(&self, s: SurfaceHandle) -> Option<WindowTarget>;
    fn on_surface_target_ready(
        &self,
        _s: SurfaceHandle,
        ready: Box<dyn FnOnce() + Send>,
    );
    fn set_surface_visibility(
        &self,
        s: SurfaceHandle,
        visibility: Visibility,
    ) -> VisibilityCommit;
    fn apply_stack(&self, ordered: &[SurfaceHandle]);
    fn menu_delivery(&self, kind: MenuKind) -> MenuDelivery<'_>;
    fn osr_popup_surface(&self) -> &dyn OsrPopupSurface;
    fn mpv_host(&self) -> &dyn MpvHost;
    fn cef_host(&self) -> Option<&dyn CefHost>;
    fn media_session(&self) -> &dyn MediaSink;
    fn cef_paths(&self) -> CefPaths;
    fn set_fullscreen(&self, v: bool);
    fn toggle_fullscreen(&self);
    fn titlebar_controls(&self) -> Option<&dyn TitlebarControls>;
    fn resize_gate(&self) -> Option<&dyn ResizeGate>;
    fn scale(&self) -> Scale;
    fn display_scale(&self, at: Option<WindowPos>) -> Scale;
    fn query_window_position(&self) -> Option<WindowPos>;
    fn window_owner(&self) -> WindowOwner<'_>;
    fn clamp_window_geometry(&self, g: WindowGeometry) -> WindowGeometry;
    fn pump(&self);
    fn run_main_loop(&self);
    fn wake_main_loop(&self);
    fn set_cursor(&self, shape: cursor::CursorShape);
    fn set_idle_inhibit(&self, level: IdleInhibitLevel);
    fn set_theme_color(&self, rgb: u32);
    fn window_decorations_supported(&self) -> bool;
    fn effective_decorations(&self) -> EffectiveDecorations;
    fn shared_texture_supported(&self) -> bool;
    fn cef_init_precedes_mpv_window(&self) -> bool;
    fn set_shared_texture_unsupported(&self);
    fn clipboard_read_text_async(&self, on_done: OnText);
    fn clipboard_write_text(&self, text: &str);
    fn primary_selection(&self) -> Option<&dyn PrimarySelection>;
    fn web_paste_reads_clipboard(&self) -> bool;
    fn open_external_url(&self, url: &str);
    fn open_path(&self, path: &Path);
    fn run_blocking(&self, f: Box<dyn FnOnce() + Send>) -> Result<(), BlockingError>;
    fn install_shutdown_handler(&self, on_shutdown: fn());
}

impl PreparedPlatform {
    pub fn initialize(
        self,
        mpv: *mut c_void,
        app: std::sync::Arc<App>,
    ) -> Result<PlatformRuntime, (PlatformInitError, Self)>;
}
```

### src/platform_abi/src/menu.rs
```rust
pub struct MenuRequest {
    pub groups: Arc<Vec<Vec<Item>>>,
    pub anchor: LogicalPoint,
    pub width: Option<NonZeroU32>,
    current: Option<usize>,
    on_closed: Vec<ChannelValue>,
}

impl MenuRequest {
    pub fn current(&self) -> Option<usize>;
    pub fn select(self, row: usize) -> Result<(), Box<dyn std::error::Error>>;
}

impl From<MenuBuilder> for MenuRequest;

impl Drop for MenuRequest;
```

## Deletions

### src/jfn_cef/src/app.rs
```rust
struct PopupOptions {
    options: Vec<String>,
    selected: i32,
    selectable: Vec<i32>,
    anchor: Option<(i32, i32)>,
}
```

### src/jfn_cef/src/app_menu.rs
```rust
#[derive(Clone)]
pub struct ApplicationMenu {
    pub items: Vec<jfn_platform_abi::MenuItem>,
    pub on_selected: Arc<dyn Fn(i32) -> bool + Send + Sync>,
}

pub(crate) fn build_closure(
    items: Vec<jfn_platform_abi::MenuItem>,
) -> Box<crate::client::ContextBuilderFn>;

pub(crate) fn dispatch_closure(
    on_selected: Arc<dyn Fn(i32) -> bool + Send + Sync>,
) -> Box<crate::client::ContextDispatcherFn>;
```

### src/jfn_cef/src/business_web.rs
```rust
pub(crate) fn install(client: &Arc<Inner>, application_menu: crate::ApplicationMenu);

fn handle_message(message: BrowserMessage) -> bool;
```

### src/jfn_cef/src/client/callbacks.rs
```rust
impl Inner {
    pub(crate) fn menu_selection_callback(
        self: &Arc<Self>,
        session: Session,
    ) -> MenuSelection;
    fn dispatch_menu_result(self: &Arc<Self>, session: Session, id: c_int);
    fn dispatch_menu_command(&self, id: c_int);
    fn take_pending_menu_callback(&self) -> Option<RunContextMenuCallback>;
    pub(crate) fn store_pending_menu_callback(&self, cb: RunContextMenuCallback);
    pub(crate) fn has_context_menu_builder(&self) -> bool;
    pub(crate) fn invoke_context_menu_builder(&self, menu_model_raw: *mut c_void);
    fn invoke_context_menu_dispatcher(&self, command_id: c_int) -> bool;
}
```

### src/jfn_cef/src/client/popup.rs
```rust
fn options_as_items(options: &[String]) -> Vec<MenuItem>;

impl Inner {
    pub(crate) fn set_popup_options(
        self: &Arc<Self>,
        opts: Vec<String>,
        selected: i32,
        selectable: Vec<i32>,
        anchor: Option<(i32, i32)>,
    );
    fn dispatch_popup_selection(&self, idx: i32, current: i32, selectable: &[i32]);
}
```

### src/jfn_cef/src/client.rs
```rust
pub(crate) struct Inner {
    pub(crate) session: Arc<crate::runtime::Session>,
    name: Mutex<String>,
    _owner_connected: Sender<Infallible>,
    owner_disconnected: Receiver<Infallible>,
    painting: Mutex<Painting>,
    browser: Mutex<BrowserState>,
    pending_menu_callback: Mutex<Option<RunContextMenuCallback>>,
    menu: Mutex<MenuOwnership>,
    surface: Arc<WebOverlaySurface>,
    width: AtomicI32,
    height: AtomicI32,
    scale: AtomicCell<Option<jfn_platform_abi::Scale>>,
    pub(super) paint_mode: PaintMode,
    paint_scheduler: PaintScheduler,
    pub(crate) frame_rate: AtomicCell<Option<FrameRate>>,
    resize_scheduled: AtomicBool,
    last_was_resized_ns: AtomicI64,
    popup: Mutex<PopupState>,
    deferred_navigation: Arc<DeferredNavigation>,
    message_handler: Mutex<Option<Box<MessageFn>>>,
    created_callback: Mutex<Option<Arc<CreatedFn>>>,
    context_menu_builder: Mutex<Option<Box<ContextBuilderFn>>>,
    context_menu_dispatcher: Mutex<Option<Box<ContextDispatcherFn>>>,
}

#[derive(Default)]
struct PopupState {
    x: i32,
    y: i32,
    w: i32,
    h: i32,
    visible: bool,
    options: Vec<String>,
    selected_idx: i32,
    selectable: Vec<i32>,
    anchor: Option<(i32, i32)>,
    size_received: bool,
    options_received: bool,
}

impl Inner {
    pub(crate) fn new(
        session: Arc<crate::runtime::Session>,
        surface: Arc<WebOverlaySurface>,
        deferred_navigation: Arc<DeferredNavigation>,
        paint_mode: PaintMode,
        frame_rate: Option<FrameRate>,
    ) -> Arc<Self>;
    pub(crate) fn menu_open(&self) -> Option<Session>;
    pub(crate) fn menu_resolve(&self, session: Session) -> bool;
    pub(crate) fn menu_reset(&self);
    pub(crate) fn set_context_menu_builder(&self, f: Option<Box<ContextBuilderFn>>);
    pub(crate) fn set_context_menu_dispatcher(
        &self,
        f: Option<Box<ContextDispatcherFn>>,
    );
}
```

### src/jfn_cef/src/client_impl/context_menu.rs
```rust
fn strip_accelerator(s: &str) -> String;
```

### src/jfn_cef/src/menu_ownership.rs
```rust
#[derive(Default)]
pub struct MenuOwnership {
    sessions: SlotMap<Session, ()>,
    current: Option<Session>,
}

impl MenuOwnership {
    pub fn open(&mut self) -> Option<Session>;
    pub fn resolve(&mut self, h: Session) -> bool;
    pub fn reset(&mut self);
}

#[test]
fn open_from_idle_grants();

#[test]
fn second_open_while_open_refused();

#[test]
fn resolve_current_then_idle();

#[test]
fn resolve_stale_is_noop_and_keeps_current();

#[test]
fn reset_clears();
```

### src/jfn_cef/src/runtime.rs
```rust
pub struct InitOptions {
    pub log_severity: LogSeverity,
    pub remote_debugging_port: DebuggingPort,
    pub disable_gpu_compositing: bool,
}
```

### src/jfn_cef/src/web_overlay.rs
```rust
pub struct WebOverlayConfig {
    pub on_event: crate::WebEventHandler,
    pub application_menu: crate::ApplicationMenu,
    pub frame_rate: Option<RefreshRate>,
    pub shared_textures: bool,
}

struct Overlay {
    application_menu: Mutex<Option<crate::ApplicationMenu>>,
    session: Arc<crate::runtime::Session>,
    platform: Mutex<Option<jfn_platform_abi::PlatformLease>>,
    subscription: Mutex<Option<jfn_input::ShellStateSubscription>>,
    close: Mutex<()>,
    window_subscription: Mutex<Option<jfn_platform_abi::WindowSubscription>>,
    client: OnceLock<Weak<Inner>>,
    deferred_navigation: Arc<DeferredNavigation>,
    paint_mode: PaintMode,
    frame_rate: AtomicCell<Option<FrameRate>>,
}
```

### src/jfn_rust/src/app.rs
```rust
fn initialize_cef(
    runtime: BrowserCef,
    platform: &jfn_platform_abi::PlatformRuntime,
    opts: &StartupOptions,
) -> Result<CefInit, jfn_cef::InitError>;

impl StartupResources<MpvNative> {
    fn initialize(
        mut self,
    ) -> Result<
        StartupResources<InitializedNative>,
        jfn_platform_abi::PlatformInitError,
    >;
}

fn start_web_overlay(
    rate: Option<jfn_gpu_paint::RefreshRate>,
    cef: &CefInit,
    user_video_bg: u32,
) -> Result<StartedOverlay, OverlayStartupError>;

fn run_app(
    instance: &Instance,
    opts: StartupOptions,
    runtime: BrowserCef,
    metadata: ApplicationMetadata,
) -> c_int;

fn run_with_cef(
    boot: ReadyBoot,
    deferred: Option<BrowserCef>,
    mut resources: StartupResources<InitializedNative>,
    opts: &StartupOptions,
    instance: &Instance,
) -> c_int;
```

### src/jfn_rust/src/app_menu.rs
```rust
fn items(restricted: bool) -> Vec<MenuItem>;

fn dispatch(id: i32) -> bool;

fn open_host(point: LogicalPoint, restricted: bool);

pub(crate) fn shell_actions() -> crate::shell::ApplicationActions;

pub(crate) fn cef_menu() -> jfn_cef::ApplicationMenu;

#[test]
fn restricted_menu_keeps_fullscreen_and_exit_but_omits_settings();
```

### src/jfn_rust/src/shell/actor.rs
```rust
pub enum Work {
    Event(Event),
    Resize { extent: WindowExtent },
    Redraw,
    OpenAbout,
    OpenClientSettings,
    Chrome(ChromeInputs),
    ChromeBackground(iced_core::Color),
    SelectionText { reader: Reader, text: Option<String> },
    ContextMenu(LogicalPoint),
    EditMenuAtCaret,
    PrimaryPaste(LogicalPoint),
    EditAt { field: Target, command: jfn_input::EditCommand },
    WebAttached(jfn_cef::WebOverlay),
    WebEvent(jfn_cef::WebEvent),
    Shutdown,
}

impl Channel {
    fn sender(&self) -> Sender<Work>;
}

impl Actor {
    pub fn spawn(
        surface: SurfaceHandle,
        channel: &Channel,
        metadata: crate::shell::metadata::ApplicationMetadata,
        actions: crate::shell::ApplicationActions,
        platform: jfn_platform_abi::PlatformLease,
        on_ready: std::sync::mpsc::SyncSender<Result<(), LoopStartError>>,
    ) -> Result<Actor, crate::shell::StartError>;
}

impl Model {
    fn view(&self) -> Element<'_, Message, Theme, iced_wgpu::Renderer>;
}

struct Loop {
    actions: crate::shell::ApplicationActions,
    surface: SurfaceHandle,
    wake_tx: Sender<Work>,
    painter: Painter,
    model: Model,
    cache: user_interface::Cache,
    events: Vec<Event>,
    cursor: Cursor,
    waker: shell::Waker,
    redraw: Redraw,
    current: WindowExtent,
    focus: FocusMemory,
    pending: Deadline,
    immediate: bool,
    batch: Vec<Work>,
    queued: Vec<Apply>,
    deferred: Vec<Deferred>,
    last_primary: Option<(Id, u64)>,
    drew_nothing_yet: bool,
}

fn run(
    surface: SurfaceHandle,
    rx: &Receiver<Work>,
    wake_tx: &Sender<Work>,
    metadata: crate::shell::metadata::ApplicationMetadata,
    actions: crate::shell::ApplicationActions,
    on_ready: std::sync::mpsc::SyncSender<Result<(), LoopStartError>>,
);

impl Loop {
    fn start(
        surface: SurfaceHandle,
        wake_tx: &Sender<Work>,
        target: jfn_gpu_paint::WindowTarget,
        metadata: crate::shell::metadata::ApplicationMetadata,
        actions: crate::shell::ApplicationActions,
    ) -> Result<Loop, LoopStartError>;
}

fn resolve_deferred(
    ui: &mut Ui<'_>,
    painter: &mut Painter,
    model: &Model,
    deferred: &mut Vec<Deferred>,
    queued: &mut Vec<Apply>,
    wake_tx: &Sender<Work>,
    actions: crate::shell::ApplicationActions,
);

fn raise_menu(
    fields: &Fields,
    p: LogicalPoint,
    queued: &mut Vec<Apply>,
    restricted: bool,
    actions: crate::shell::ApplicationActions,
) -> Option<LogicalPoint>;
```

### src/jfn_rust/src/shell/connect.rs
```rust
impl Connect {
    pub fn view<'a>(
        &'a self,
        screen: &'a Screen,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn form_view<'a>(
        &'a self,
        url: &'a str,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn failure_view(&self) -> Element<'_, Message, Theme, iced_wgpu::Renderer>;
}
```

### src/jfn_rust/src/shell/field.rs
```rust
pub struct Field<'a, Message> {
    id: Id,
    placeholder: &'a str,
    value: &'a str,
    on_input: Option<Box<dyn Fn(String) -> Message + 'a>>,
    on_submit: Option<Message>,
    on_unfocus: Option<Message>,
    padding: Padding,
    size: Option<Pixels>,
    width: Length,
}

pub fn field<'a, Message>(
    id: Id,
    placeholder: &'a str,
    value: &'a str,
) -> Field<'a, Message>;

impl<'a, Message: Clone + 'a> Field<'a, Message> {
    fn placeholder_text(&self, renderer: &Renderer, bounds: Size) -> Text<&'a str, Font>;
}
```

### src/jfn_rust/src/shell/lang.rs
```rust
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Strings {
    pub server_host: &'static str,
    pub server_host_help: &'static str,
    pub connect: &'static str,
    pub connection_failure: &'static str,
    pub unable_to_connect: &'static str,
    pub got_it: &'static str,
    pub undo: &'static str,
    pub redo: &'static str,
    pub cut: &'static str,
    pub copy: &'static str,
    pub paste: &'static str,
    pub select_all: &'static str,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct EditEntry {
    pub lang: &'static str,
    pub undo: &'static str,
    pub redo: &'static str,
    pub cut: &'static str,
    pub copy: &'static str,
    pub paste: &'static str,
    pub select_all: &'static str,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Entry {
    pub lang: &'static str,
    pub header_connect_to_server: Option<&'static str>,
    pub label_server_host: Option<&'static str>,
    pub label_server_host_help: Option<&'static str>,
    pub connect: Option<&'static str>,
    pub header_connection_failure: Option<&'static str>,
    pub message_unable_to_connect_to_server: Option<&'static str>,
    pub button_got_it: Option<&'static str>,
}

fn find(lang: &str) -> Option<&'static Entry>;

#[allow(clippy::expect_used)]
fn fallback() -> &'static Entry;

pub fn entry_for(locale: &str) -> &'static Entry;

pub fn strings_for(locale: &str) -> Strings;

fn edit_entry_for(locale: &str) -> &'static EditEntry;

pub fn strings() -> &'static Strings;

pub fn system_locale() -> String;

#[test]
fn every_language_is_present();

#[test]
fn exact_tag_wins_over_primary_subtag();

#[test]
fn missing_host_label_falls_back_per_field();
```

### src/jfn_rust/src/shell/menu.rs
```rust
impl Item {
    pub fn label(self, strings: &Strings) -> &'static str;
    fn id(self) -> c_int;
    fn from_id(id: c_int) -> Option<Item>;
}

pub fn open_edit(field: &Snapshot, anchor: LogicalPoint, strings: &Strings);

#[test]
fn edit_command_ids_round_trip_without_using_native_cancellation_ids();
```

### src/jfn_rust/src/shell/mod.rs
```rust
#[derive(Clone, Copy)]
pub struct ApplicationActions {
    pub open_menu: fn(jfn_platform_abi::LogicalPoint, bool),
}

pub fn shell_start(
    platform: &jfn_platform_abi::PlatformRuntime,
    metadata: metadata::ApplicationMetadata,
    actions: ApplicationActions,
) -> Result<(Shell, Readiness), StartError>;

pub fn shell_open_about();

pub fn shell_open_client_settings();
```

### src/jfn_rust/src/shell/modal.rs
```rust
impl Stack {
    pub fn view<'a>(
        &'a self,
        screen: &'a Screen,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
}
```

### src/jfn_rust/src/shell/settings.rs
```rust
impl Settings {
    pub fn view(&self) -> Element<'_, Message, Theme, iced_wgpu::Renderer>;
    fn group<'a>(
        &self,
        title: &'a str,
        controls: iced_widget::Column<'a, Message, Theme, iced_wgpu::Renderer>,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn setting<'a>(
        &self,
        label: &'a str,
        control: Element<'a, Message, Theme, iced_wgpu::Renderer>,
        help: &'a str,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn selection<'a>(
        &self,
        label: &'a str,
        control: Element<'a, Message, Theme, iced_wgpu::Renderer>,
        help: &'a str,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn toggle<'a>(
        &self,
        id: Id,
        label: &'a str,
        value: bool,
        changed: fn(bool) -> Message,
        help: &'a str,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
    fn action<'a>(
        &self,
        id: Id,
        label: &'a str,
        message: Message,
    ) -> Element<'a, Message, Theme, iced_wgpu::Renderer>;
}

fn audio_channel_label(value: &str) -> String;

fn log_level_label(value: &str) -> String;

fn decoration_label(value: &Option<WindowDecorations>) -> String;
```

### src/jfn_rust/src/shell/settings_overlay.rs
```rust
impl SettingsOverlay {
    pub fn view(&self) -> Element<'_, Message, Theme, iced_wgpu::Renderer>;
}
```

### src/linux_util/src/menu/engine.rs
```rust
struct Resolve {
    selection: MenuSelection,
    id: c_int,
}

impl Resolve {
    fn dismissed(selection: MenuSelection) -> Resolve;
}

struct Menu {
    items: Arc<Vec<MenuItem>>,
    fsm: FsmState,
    laid: Option<Laid>,
    width: c_int,
    on_selected: Option<MenuSelection>,
    anchor: LogicalPoint,
}

enum Job {
    Shape { generation: Generation, items: Arc<Vec<MenuItem>>, width: i32 },
    Paint {
        generation: Generation,
        items: Arc<Vec<MenuItem>>,
        layout: Arc<Layout>,
        active: i32,
    },
}

fn clear_menu(state: &mut MenuState) -> Option<MenuSelection>;

fn request_row(items: Vec<MenuItem>, initial: c_int) -> (MenuRequest, Receiver<c_int>);

fn request(items: Vec<MenuItem>) -> (MenuRequest, Receiver<c_int>);

fn selectable_item() -> MenuItem;
```

### src/linux_util/src/menu/interaction_fsm.rs
```rust
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum MenuEffect {
    Redraw,
    Close(i32),
}

pub fn step(
    s: &mut MenuState,
    ev: &MenuEvent,
    layout: Option<&Layout>,
    items: &[MenuItem],
) -> Vec<MenuEffect>;

fn selectable(items: &[MenuItem], active: i32) -> Option<i32>;

fn item(id: i32) -> MenuItem;

fn sep() -> MenuItem;

fn disabled(id: i32) -> MenuItem;

fn fixture() -> (Vec<MenuItem>, Layout);

#[test]
fn motion_onto_separator_clears();

#[test]
fn press_on_separator_ignored();
```

### src/linux_util/src/menu/render.rs
```rust
#[derive(Clone)]
pub struct Row {
    pub item: usize,
    pub y: i32,
    pub h: i32,
    pub separator: bool,
    pub enabled: bool,
}

#[derive(Clone)]
pub struct Layout {
    pub width: i32,
    pub height: i32,
    pub rows: Vec<Row>,
    pub selectable: Vec<usize>,
    scale: Scale,
}

pub fn layout(fonts: &mut Fonts, items: &[MenuItem], scale: Scale) -> Option<Layout>;

pub fn paint(
    fonts: &mut Fonts,
    layout: &Layout,
    items: &[MenuItem],
    active: i32,
) -> Option<Pixmap>;
```

### src/macos/src/init.rs
```rust
pub fn macos_init(_mpv: *mut c_void) -> Result<(), jfn_platform_abi::PlatformInitError>;
```

### src/macos/src/ns_menu.rs
```rust
pub(crate) struct MenuEntry {
    pub title: String,
    pub tag: c_int,
    pub enabled: bool,
    pub separator: bool,
    pub checked: bool,
}

pub(crate) struct MenuSpec {
    pub entries: Vec<MenuEntry>,
    pub x: c_int,
    pub y: c_int,
    pub positioning_tag: Option<c_int>,
    pub min_width: Option<c_int>,
}

struct SelectionCb {
    fired: Mutex<Option<MenuSelection>>,
}

pub(crate) fn present_on_main(spec: MenuSpec, on_selected: Option<MenuSelection>);
```

### src/platform_abi/src/lib.rs
```rust
pub trait Platform: Send + Sync {
    fn display(&self) -> DisplayBackend;
    fn default_window_decorations(&self) -> WindowDecorations;
    fn window_decoration_options(&self) -> DecorationOptions;
    fn resolve_window_decorations(
        &self,
        configured: Option<WindowDecorations>,
    ) -> WindowDecorations;
    fn early_init(&self);
    fn init(
        &self,
        access: &LifecycleAccess,
        mpv: *mut c_void,
    ) -> Result<(), PlatformInitError>;
    fn cleanup(&self, access: &LifecycleAccess);
    fn post_window_cleanup(&self, access: &LifecycleAccess);
    fn alloc_surface(&self, initial: Visibility) -> SurfaceHandle;
    fn free_surface(&self, s: SurfaceHandle);
    fn surface_present<'a>(
        &self,
        s: SurfaceHandle,
        frame: PaintFrame<'a>,
    ) -> Result<Presented, PaintFrame<'a>>;
    fn surface_resize(&self, s: SurfaceHandle, size: SurfaceSize);
    fn surface_window_target(&self, s: SurfaceHandle) -> Option<WindowTarget>;
    fn on_surface_target_ready(
        &self,
        _s: SurfaceHandle,
        ready: Box<dyn FnOnce() + Send>,
    );
    fn set_surface_visibility(
        &self,
        s: SurfaceHandle,
        visibility: Visibility,
    ) -> VisibilityCommit;
    fn apply_stack(&self, ordered: &[SurfaceHandle]);
    fn menu_delivery(&self, kind: MenuKind) -> MenuDelivery<'_>;
    fn osr_popup_surface(&self) -> &dyn OsrPopupSurface;
    fn mpv_host(&self) -> &dyn MpvHost;
    fn cef_host(&self) -> Option<&dyn CefHost>;
    fn media_session(&self) -> &dyn MediaSink;
    fn cef_paths(&self) -> CefPaths;
    fn set_fullscreen(&self, v: bool);
    fn toggle_fullscreen(&self);
    fn titlebar_controls(&self) -> Option<&dyn TitlebarControls>;
    fn resize_gate(&self) -> Option<&dyn ResizeGate>;
    fn scale(&self) -> Scale;
    fn display_scale(&self, at: Option<WindowPos>) -> Scale;
    fn query_window_position(&self) -> Option<WindowPos>;
    fn window_owner(&self) -> WindowOwner<'_>;
    fn clamp_window_geometry(&self, g: WindowGeometry) -> WindowGeometry;
    fn pump(&self);
    fn run_main_loop(&self);
    fn wake_main_loop(&self);
    fn set_cursor(&self, shape: cursor::CursorShape);
    fn set_idle_inhibit(&self, level: IdleInhibitLevel);
    fn set_theme_color(&self, rgb: u32);
    fn window_decorations_supported(&self) -> bool;
    fn effective_decorations(&self) -> EffectiveDecorations;
    fn shared_texture_supported(&self) -> bool;
    fn cef_init_precedes_mpv_window(&self) -> bool;
    fn set_shared_texture_unsupported(&self);
    fn clipboard_read_text_async(&self, on_done: OnText);
    fn clipboard_write_text(&self, text: &str);
    fn primary_selection(&self) -> Option<&dyn PrimarySelection>;
    fn web_paste_reads_clipboard(&self) -> bool;
    fn open_external_url(&self, url: &str);
    fn open_path(&self, path: &Path);
    fn run_blocking(&self, f: Box<dyn FnOnce() + Send>) -> Result<(), BlockingError>;
    fn install_shutdown_handler(&self, on_shutdown: fn());
}

pub fn set_about_handler(f: fn());

pub fn request_about();

pub fn set_client_settings_handler(f: fn());

pub fn request_client_settings();

impl PreparedPlatform {
    pub fn initialize(
        self,
        mpv: *mut c_void,
    ) -> Result<PlatformRuntime, (PlatformInitError, Self)>;
}
```

### src/platform_abi/src/menu.rs
```rust
pub struct MenuSelection {
    resolve: Option<Box<dyn FnOnce(c_int) + Send>>,
}

impl MenuSelection {
    pub fn new(f: impl FnOnce(c_int) + Send + 'static) -> MenuSelection;
    pub fn resolve(mut self, id: c_int);
}

impl Drop for MenuSelection;

#[derive(Clone)]
pub struct MenuItem {
    pub id: c_int,
    pub label: String,
    pub enabled: bool,
    pub separator: bool,
}

pub fn menu_has_selectable(items: &[MenuItem]) -> bool;

pub fn menu_initial_row(items: &[MenuItem], initial: c_int) -> c_int;

pub struct MenuRequest {
    pub items: Vec<MenuItem>,
    pub x: c_int,
    pub y: c_int,
    pub width: c_int,
    pub initial: c_int,
    pub on_selected: MenuSelection,
}

fn item(id: c_int, enabled: bool, separator: bool) -> MenuItem;

fn recorder() -> (Arc<Mutex<Vec<c_int>>>, MenuSelection);

#[test]
fn a_dropped_selection_resolves_as_dismissed();

#[test]
fn a_resolved_selection_fires_once_with_its_id();

#[test]
fn separators_and_disabled_items_are_not_selectable();

#[test]
fn an_initial_row_survives_only_when_it_is_selectable();
```

### src/windows/src/menu.rs
```rust
struct Pending {
    items: Vec<MenuItem>,
    x: c_int,
    y: c_int,
    on_selected: MenuSelection,
}
```
