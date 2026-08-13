import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

export default function App() {
  return (
    <Card className="max-w-sm mx-auto mt-20">
      <CardContent className="pt-6 text-center space-y-4">
        <h1 className="text-xl font-bold">晓问 · 差旅助手</h1>
        <p className="text-muted-foreground text-sm">React 19 + Vite + Tailwind v4 + shadcn/ui 脚手架验证</p>
        <Button>开始</Button>
      </CardContent>
    </Card>
  )
}
