import React from 'react'
import { motion } from 'framer-motion'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'react-hot-toast'
import { Settings as SettingsIcon, Moon, Sun, Loader2, Pencil, AlertTriangle, Lock } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/Dialog'
import { Label } from '@/components/ui/Label'
import { Badge } from '@/components/ui/Badge'
import { configApi } from '@/lib/api'

export function SettingsPage() {
  const queryClient = useQueryClient()

  const { data: configItems, isLoading } = useQuery({
    queryKey: ['config-list'],
    queryFn: configApi.list,
  })

  const [selectedKey, setSelectedKey] = React.useState<string | null>(null)
  const [editValue, setEditValue] = React.useState<string>('')
  const [editDesc, setEditDesc] = React.useState<string>('')
  const [search, setSearch] = React.useState('')
  const [categoryFilter, setCategoryFilter] = React.useState('ALL')

  const updateMutation = useMutation({
    mutationFn: ({ key, value, description }: { key: string; value: any; description?: string }) =>
      configApi.update(key, value, description),
    onSuccess: () => {
      toast.success('저장되었습니다')
      queryClient.invalidateQueries({ queryKey: ['config-list'] })
      setSelectedKey(null)
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || '저장에 실패했습니다')
    },
  })

  const openEdit = (item: any) => {
    setSelectedKey(item.key)
    setEditValue(String(item.value ?? ''))
    setEditDesc('')
  }

  const saveEdit = () => {
    if (!selectedKey) return
    updateMutation.mutate({ key: selectedKey, value: editValue, description: editDesc || undefined })
  }

  const renderSource = (item: any) => {
    if (item.sensitive) {
      if (item.source === 'env') return <Badge variant="destructive">secret(env)</Badge>
      if (item.source === 'secret') return <Badge variant="outline">secret(file)</Badge>
      return <Badge variant="secondary">secret(unset)</Badge>
    }
    if (item.source === 'env') return <Badge variant="destructive">env</Badge>
    if (item.source === 'db') return <Badge variant="default">db</Badge>
    return <Badge variant="secondary">default</Badge>
  }

  const categories = React.useMemo(() => {
    const set = new Set<string>()
    configItems?.forEach((i: any) => set.add(i.category || 'General'))
    return ['ALL', ...Array.from(set)]
  }, [configItems])

  const filteredItems = React.useMemo(() => {
    return (configItems || []).filter((i: any) => {
      const matchSearch =
        i.key.toLowerCase().includes(search.toLowerCase()) ||
        (i.desc || '').toLowerCase().includes(search.toLowerCase())
      const matchCategory = categoryFilter === 'ALL' || i.category === categoryFilter
      return matchSearch && matchCategory
    })
  }, [configItems, search, categoryFilter])

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-6 max-w-5xl"
    >
      <div>
        <h1 className="text-3xl font-display font-bold flex items-center gap-3">
          <SettingsIcon className="w-8 h-8 text-muted-foreground" />
          Settings
        </h1>
        <p className="text-muted-foreground mt-1">대시보드 및 트레이딩 설정을 관리합니다</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Moon className="w-5 h-5" />
            테마
          </CardTitle>
          <CardDescription>대시보드 테마를 설정합니다</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-3">
            <Button variant="default" className="gap-2">
              <Moon className="w-4 h-4" />
              다크 모드
            </Button>
            <Button variant="outline" className="gap-2" disabled>
              <Sun className="w-4 h-4" />
              라이트 모드 (준비 중)
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SettingsIcon className="w-5 h-5" />
            시스템 설정 (env > db > default)
          </CardTitle>
          <CardDescription>레지스트리 기반 설정을 조회/수정합니다. env로 설정된 키는 읽기 전용입니다.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2 items-center">
            <Input
              placeholder="키/설명 검색"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="max-w-sm"
            />
            <select
              className="border border-border rounded-md px-2 py-1 text-sm bg-background"
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
            >
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          {isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" />
              불러오는 중...
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm border border-border/50 rounded-md">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="px-3 py-2 text-left">Key</th>
                    <th className="px-3 py-2 text-left">Value</th>
                    <th className="px-3 py-2 text-left">Source</th>
                    <th className="px-3 py-2 text-left">Default</th>
                    <th className="px-3 py-2 text-left">Category</th>
                    <th className="px-3 py-2 text-left">Desc</th>
                    <th className="px-3 py-2 text-left">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((item: any) => {
                    const displayValue = item.sensitive
                      ? item.source === 'default'
                        ? '(unset)'
                        : '***'
                      : String(item.value)
                    return (
                      <tr key={item.key} className="border-t border-border/50">
                        <td className="px-3 py-2 font-mono text-xs">{item.key}</td>
                        <td className="px-3 py-2">{displayValue}</td>
                        <td className="px-3 py-2">{renderSource(item)}</td>
                        <td className="px-3 py-2 text-muted-foreground text-xs">{String(item.default ?? '')}</td>
                        <td className="px-3 py-2">{item.category}</td>
                        <td className="px-3 py-2 text-muted-foreground text-xs">{item.desc}</td>
                        <td className="px-3 py-2">
                          {item.sensitive ? (
                            <Badge variant="outline" className="gap-1 text-xs">
                              <Lock className="w-3 h-3" />
                              secret
                            </Badge>
                          ) : item.source === 'env' ? (
                            <Badge variant="outline" className="gap-1 text-xs">
                              <AlertTriangle className="w-3 h-3" />
                              env 고정
                            </Badge>
                          ) : (
                            <Button
                              variant="outline"
                              size="sm"
                              className="gap-1"
                              onClick={() => openEdit(item)}
                            >
                              <Pencil className="w-4 h-4" />
                              편집
                            </Button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!selectedKey} onOpenChange={(open) => !open && setSelectedKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>설정 수정</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Key</Label>
              <Input value={selectedKey || ''} disabled className="bg-muted" />
            </div>
            <div>
              <Label>Value</Label>
              <Input value={editValue} onChange={(e) => setEditValue(e.target.value)} />
            </div>
            <div>
              <Label>설명 (선택)</Label>
              <Input
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
                placeholder="DB description 필드에 저장 (옵션)"
              />
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setSelectedKey(null)}>
              취소
            </Button>
            <Button onClick={saveEdit} disabled={updateMutation.isPending}>
              {updateMutation.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              저장
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </motion.div>
  )
}

