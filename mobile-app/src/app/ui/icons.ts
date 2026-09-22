/**
 * The icon set: Phosphor, under the names this codebase already calls them by.
 *
 * The frozen reference client draws every icon from `@phosphor-icons/react`, aliased to the names the Figma
 * export used - `House as Home`, `CaretRight as ChevronRight`, `PaperPlaneTilt as Send`. This client was on
 * Lucide, so the two products drew the same thing in two different hands: Lucide's open, rounded geometry
 * against Phosphor's closed, even-weight one. Side by side they do not look like one app.
 *
 * So the set moves, and the alias map is the whole of the change. Screens keep importing `MapPin` and
 * `ChevronRight` from here and never learn which library is underneath, which is also what makes this
 * reversible.
 *
 * Two practical notes for a caller:
 *
 * - Weight, not stroke width. Phosphor ships `thin | light | regular | bold | fill | duotone` and takes a
 *   `weight` prop; there is no `strokeWidth`. `regular` is the default and is what the reference client uses
 *   everywhere except its seal, which is `fill`.
 * - `Loader2` is now `CircleNotch`, which is drawn as an open ring rather than a two-thirds arc. It still
 *   needs `animate-spin` from the caller - neither library spins on its own.
 *
 * Names marked "(this client)" have no counterpart in the frozen client because it has no such screen; they
 * were chosen from the same family so the set stays visually one thing.
 */
export type { Icon, IconProps, IconWeight } from "@phosphor-icons/react";

export {
  Pulse as Activity,
  WarningCircle as AlertCircle,
  Warning as AlertTriangle,  // (this client)
  Archive,  // (this client)
  ArrowLeft,  // (this client)
  ArrowRight,
  ArrowUpRight,
  SealCheck as BadgeCheck,  // (this client)
  Prohibit as Ban,
  Money as Banknote,  // (this client)
  ChartBar as BarChart3,  // (this client)
  Bell,
  Buildings as Building2,  // (this client)
  Calendar,  // (this client)
  Camera,
  Car,
  Check,  // (this client)
  Checks as CheckCheck,
  CheckCircle,  // (this client)
  CheckCircle as CheckCircle2,
  CaretDown as ChevronDown,
  CaretLeft as ChevronLeft,
  CaretRight as ChevronRight,
  CaretDoubleLeft as ChevronsLeft,  // (this client)
  CaretDoubleRight as ChevronsRight,  // (this client)
  CurrencyCircleDollar as CircleDollarSign,  // (this client)
  RadioButton as CircleDot,
  ClipboardText as ClipboardList,
  Clock,
  CreditCard,
  Crosshair,  // (this client)
  CurrencyDollar as DollarSign,
  DownloadSimple as Download,
  PencilSimple as Edit,  // (this client)
  PencilSimple as Edit3,
  ArrowSquareOut as ExternalLink,
  Eye,
  EyeSlash as EyeOff,
  ClockCounterClockwise as FileClock,  // (this client)
  FileText,
  Funnel as Filter,
  Flag,
  Globe,
  Headphones,
  House as Home,
  Image,
  Tray as Inbox,
  Info,
  Key as KeyRound,  // (this client)
  SquaresFour as LayoutDashboard,
  Lifebuoy as LifeBuoy,  // (this client)
  CircleNotch as Loader2,  // (this client)
  Crosshair as Locate,
  CrosshairSimple as LocateFixed,  // (this client)
  Lock,
  SignOut as LogOut,
  MapPin,
  MapTrifold as MapPinned,  // (this client)
  List as Menu,
  Monitor,
  Moon,
  NavigationArrow as Navigation,
  Package,
  Sidebar as PanelLeft,
  SidebarSimple as PanelLeftClose,
  Pencil,
  Percent,  // (this client)
  Phone,
  Plus,
  ArrowsClockwise as RefreshCw,
  Path as Route,
  FloppyDisk as Save,  // (this client)
  Scales as Scale,  // (this client)
  SealCheck,
  SealWarning,
  MagnifyingGlass as Search,
  PaperPlaneTilt as Send,
  Gear as Settings,
  Shield,
  ShieldWarning as ShieldAlert,  // (this client)
  ShieldCheck,
  ShieldSlash as ShieldOff,  // (this client)
  SlidersHorizontal,  // (this client)
  Star,
  Sun,
  Tag,
  ThumbsUp,
  ToggleLeft,
  ToggleRight,
  Trash as Trash2,
  TrendUp as TrendingUp,
  Truck,
  LockOpen as Unlock,  // (this client)
  UploadSimple as Upload,  // (this client)
  User,
  UserCheck,
  UserPlus,  // (this client)
  UserCircle as UserRound,  // (this client)
  UserMinus as UserX,
  Users,
  UsersThree as UsersRound,  // (this client)
  Vibrate,
  Wallet as WalletCards,  // (this client)
  X,
  Lightning as Zap,
} from "@phosphor-icons/react";
