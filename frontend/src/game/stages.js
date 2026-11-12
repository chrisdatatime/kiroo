// Máquina de estados da produção (sem dependências: testável em Node; data.js reexporta).
export const STAGES = ['produto', 'direcao', 'gerar_img', 'img_gerando', 'img_revisao', 'gerar_vid', 'vid_gerando', 'vid_revisao', 'montando', 'entrega', 'exportado'];

export const STAGE_LABELS = {
  produto: 'Preparando o produto', direcao: 'Definindo a direção', gerar_img: 'Aguardando você liberar as imagens',
  img_gerando: 'Criando imagens', img_revisao: 'Revisão das imagens', gerar_vid: 'Pronto para animar',
  vid_gerando: 'Animando as cenas', vid_revisao: 'Revisão dos takes', montando: 'Montando o vídeo',
  entrega: 'Vídeo pronto para revisar', exportado: 'Exportado',
  // missões encerradas sem entrega (fora de STAGES: não têm posição no fluxo)
  cancelada: 'Missão cancelada', falhou: 'Missão falhou',
};
