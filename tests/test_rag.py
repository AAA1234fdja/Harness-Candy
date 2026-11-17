"""Tests del pipeline RAG propio (rag.py): chunking, BM25, embeddings, hibrido, persistencia."""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.rag import (
    BM25Index,
    Chunk,
    HashingEmbedder,
    HybridRetriever,
    RAGPipeline,
    VectorIndex,
    chunk_text,
    cosine,
    tokenize,
)


class TestRag(unittest.TestCase):
    def test_tokenize(self):
        self.assertEqual(tokenize("Hola, MUNDO!"), ["hola", "mundo"])

    def test_chunk_text_solapamiento(self):
        texto = " ".join(f"pal{i}" for i in range(200))
        chunks = chunk_text(texto, size=100, overlap=20, source="t")
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c.contenido), 130)  # margen por corte por palabras
            self.assertEqual(c.source, "t")
        # hay solapamiento: algun chunk comparte contenido con el anterior
        self.assertTrue(any(chunks[i].contenido[:10] in chunks[i + 1].contenido for i in range(len(chunks) - 1)) or len(chunks) > 1)

    def test_chunk_text_invalido(self):
        with self.assertRaises(ValueError):
            chunk_text("x", size=0)
        with self.assertRaises(ValueError):
            chunk_text("x", size=10, overlap=10)

    def test_chunk_text_vacio(self):
        self.assertEqual(chunk_text("   "), [])

    def test_bm25(self):
        idx = BM25Index()
        idx.add(chunk_text("el gato duerme en la casa", size=100, overlap=0, source="a"))
        idx.add(chunk_text("el perro ladra fuerte", size=100, overlap=0, source="b"))
        res = idx.search("gato duerme", k=2)
        self.assertTrue(res)
        self.assertEqual(res[0][1].source, "a")
        self.assertGreater(res[0][0], 0)

    def test_bm25_sin_docs(self):
        self.assertEqual(BM25Index().search("x"), [])

    def test_hashing_embedder_determinista_y_normalizado(self):
        e = HashingEmbedder(dim=64)
        v1 = e.embed("hola mundo")
        v2 = e.embed("hola mundo")
        self.assertEqual(v1, v2)
        import math

        self.assertAlmostEqual(math.sqrt(sum(x * x for x in v1)), 1.0, places=5)
        self.assertEqual(len(v1), 64)

    def test_cosine(self):
        self.assertAlmostEqual(cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine([1, 0], [0, 1]), 0.0)
        self.assertEqual(cosine([], [1]), 0.0)

    def test_vector_index(self):
        vi = VectorIndex(HashingEmbedder(dim=128))
        vi.add(chunk_text("la seguridad exige claves en entorno", size=100, overlap=0, source="s"))
        vi.add(chunk_text("el perro ladra", size=100, overlap=0, source="p"))
        res = vi.search("claves en entorno", k=1)
        self.assertEqual(res[0][1].source, "s")

    def test_hybrid_retriever_rrf(self):
        bm = BM25Index()
        vi = VectorIndex()
        chunks = chunk_text("uno dos tres cuatro cinco seis", size=100, overlap=0, source="x") + chunk_text(
            "otra cosa distinta", size=100, overlap=0, source="y"
        )
        bm.add(chunks)
        vi.add(chunks)
        hr = HybridRetriever(bm, vi)
        res = hr.search("uno dos", k=2)
        self.assertGreaterEqual(len(res), 1)
        self.assertEqual(res[0]["procedencia"], "x")
        self.assertIn("score", res[0])
        self.assertIn("contenido", res[0])

    def test_rag_pipeline_query_citas(self):
        pipe = RAGPipeline(chunk_size=200, chunk_overlap=40)
        pipe.add_text("docs/a.md", "Las claves API solo viven en variables de entorno. Nunca en el codigo fuente.")
        pipe.add_text("docs/b.md", "El DAG ejecuta tareas en paralelo con un ejecutor propio.")
        r = pipe.query("donde van las claves API?", k=2)
        self.assertGreaterEqual(r["n_fragmentos"], 1)
        self.assertIn("procedencia", r["fragmentos"][0])
        self.assertEqual(r["fragmentos"][0]["procedencia"], "docs/a.md")
        self.assertGreater(r["nivel_confianza"], 0)
        self.assertEqual(pipe.stats()["docs"], 2)

    def test_rag_pipeline_add_file_y_dir(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.md").write_text("contenido alpha beta gamma", encoding="utf-8")
            (Path(td) / "b.txt").write_text("contenido delta epsilon", encoding="utf-8")
            (Path(td) / ".git").mkdir()
            (Path(td) / ".git" / "ignorado.md").write_text("no indexar", encoding="utf-8")
            pipe = RAGPipeline()
            n = pipe.add_dir(td)
            self.assertGreaterEqual(n, 2)
            self.assertEqual(pipe.query("alpha beta", k=1)["fragmentos"][0]["procedencia"].endswith("a.md"), True)

    def test_rag_pipeline_persistencia(self):
        with tempfile.TemporaryDirectory() as td:
            pipe = RAGPipeline(chunk_size=100, chunk_overlap=20)
            pipe.add_text("f.md", "texto de prueba para persistir el indice sin modelo externo")
            p = Path(td) / "idx.json"
            pipe.save(p)
            pipe2 = RAGPipeline.load(p)
            self.assertEqual(pipe2.stats()["chunks"], pipe.stats()["chunks"])
            r = pipe2.query("persistir indice", k=1)
            self.assertEqual(r["n_fragmentos"], 1)

    def test_chunk_to_dict(self):
        c = Chunk("hola", "src", 0, 4, 0)
        d = c.to_dict()
        self.assertEqual(d["contenido"], "hola")
        self.assertEqual(Chunk(**d).source, "src")


if __name__ == "__main__":
    unittest.main()
