import { NextResponse } from 'next/server';
import { prisma } from '@/lib/db';

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const strategy = searchParams.get('strategy');
    const symbol = searchParams.get('symbol');

    let where: any = {};
    if (strategy) where.strategy = strategy;
    if (symbol) where.symbol = symbol;

    const runs = await prisma.runs.findMany({
      where,
      orderBy: { created_at: 'desc' }
    });

    return NextResponse.json({ rows: runs });
  } catch (error) {
    console.error("Error fetching runs:", error);
    return NextResponse.json({ rows: [] }, { status: 500 });
  }
}
