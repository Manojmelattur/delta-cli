"use client";

import { useState, useMemo } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { ChevronUp, ChevronDown, ChevronsUpDown, Search } from "lucide-react";

export type ColumnDef<T = any> = {
  key: string;
  header: string;
  sortable?: boolean;
  searchable?: boolean;
  className?: string;
  render?: (value: any, row: T) => React.ReactNode;
};

type SortDir = "asc" | "desc" | null;

interface SortableTableProps<T = any> {
  data: T[];
  columns: ColumnDef<T>[];
  loading?: boolean;
  emptyMessage?: string;
  searchPlaceholder?: string;
  defaultSort?: { key: string; dir: "asc" | "desc" };
  className?: string;
}

export function SortableTable<T extends Record<string, any>>({
  data,
  columns,
  loading = false,
  emptyMessage = "No data found.",
  searchPlaceholder = "Search...",
  defaultSort,
  className,
}: SortableTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(defaultSort?.key ?? null);
  const [sortDir, setSortDir] = useState<SortDir>(defaultSort?.dir ?? null);
  const [search, setSearch] = useState("");

  const searchableCols = columns.filter((c) => c.searchable !== false);

  function handleSort(key: string) {
    if (sortKey === key) {
      if (sortDir === "asc") {
        setSortDir("desc");
      } else if (sortDir === "desc") {
        setSortKey(null);
        setSortDir(null);
      } else {
        setSortDir("asc");
      }
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const filtered = useMemo(() => {
    if (!search.trim()) return data;
    const q = search.toLowerCase();
    return data.filter((row) =>
      searchableCols.some((col) => {
        const val = row[col.key];
        return val != null && String(val).toLowerCase().includes(q);
      })
    );
  }, [data, search]);

  const sorted = useMemo(() => {
    if (!sortKey || !sortDir) return filtered;
    return [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      const cmp =
        typeof av === "number" && typeof bv === "number"
          ? av - bv
          : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [filtered, sortKey, sortDir]);

  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 10;
  
  // reset page on search
  useMemo(() => { setCurrentPage(1); }, [search]);

  const totalPages = Math.ceil(sorted.length / pageSize);
  const paginatedRows = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return sorted.slice(start, start + pageSize);
  }, [sorted, currentPage, pageSize]);

  function SortIcon({ colKey }: { colKey: string }) {
    if (sortKey !== colKey)
      return <ChevronsUpDown className="ml-1 h-3.5 w-3.5 text-muted-foreground/50 inline" />;
    if (sortDir === "asc")
      return <ChevronUp className="ml-1 h-3.5 w-3.5 text-primary inline" />;
    if (sortDir === "desc")
      return <ChevronDown className="ml-1 h-3.5 w-3.5 text-primary inline" />;
    return <ChevronsUpDown className="ml-1 h-3.5 w-3.5 text-muted-foreground/50 inline" />;
  }

  return (
    <div className={`space-y-3 ${className ?? ""}`}>
      {/* Search bar */}
      <div className="relative max-w-sm">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder={searchPlaceholder}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-8 h-9 text-sm"
        />
      </div>

      <div className="rounded-lg border overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 hover:bg-muted/40">
              {columns.map((col, colIndex) => (
                <TableHead
                  key={`head-${colIndex}`}
                  className={`${col.className ?? ""} ${
                    col.sortable ? "cursor-pointer select-none hover:text-foreground" : ""
                  } font-semibold text-xs uppercase tracking-wider whitespace-nowrap`}
                  onClick={() => col.sortable && handleSort(col.key)}
                >
                  {col.header}
                  {col.sortable && <SortIcon colKey={col.key} />}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="text-center py-10 text-muted-foreground">
                  <div className="flex items-center justify-center gap-2">
                    <div className="h-4 w-4 rounded-full border-2 border-primary border-t-transparent animate-spin" />
                    Loading...
                  </div>
                </TableCell>
              </TableRow>
            ) : paginatedRows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} className="text-center py-10 text-muted-foreground">
                  {search ? `No results for "${search}"` : emptyMessage}
                </TableCell>
              </TableRow>
            ) : (
              paginatedRows.map((row, rowIndex) => (
                <TableRow
                  key={`row-${rowIndex}`}
                  className="hover:bg-muted/30 transition-colors"
                >
                  {columns.map((col, colIndex) => (
                    <TableCell key={`cell-${rowIndex}-${colIndex}`} className={col.className}>
                      {col.render ? col.render(row[col.key], row) : (row[col.key] ?? "—")}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {sorted.length} {sorted.length === 1 ? "row" : "rows"}
          {search ? ` matching "${search}"` : ""}
          {data.length !== sorted.length ? ` of ${data.length} total` : ""}
        </p>
        
        {totalPages > 1 && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className="px-2 py-1 text-xs border rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted transition-colors"
            >
              Previous
            </button>
            <span className="text-xs text-muted-foreground">
              Page {currentPage} of {totalPages}
            </span>
            <button
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              className="px-2 py-1 text-xs border rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted transition-colors"
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
